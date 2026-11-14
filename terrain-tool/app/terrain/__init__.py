"""Terrain screening engine (ported from the kml-terrain-screening skill).

Public API: ScreeningError, Feature, SiteInput, validate_upload, run_screening.
See docs/ARCHITECTURE.md for the contract and the result.json schema.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..config import Settings
from . import analysis, boundaries, figures, flags
from .dem import DemGrid, fetch_dem
from .kml import Feature, ScreeningError, SiteInput, validate_upload

__all__ = ["ScreeningError", "Feature", "SiteInput", "DemGrid", "validate_upload",
           "run_screening", "render_summary_md"]

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SCHEMES = {"lss", "cress", "fpv", "rooftop", "other"}
STAGES = {"exploring", "land_secured", "bidding", "other"}

Bbox = tuple[float, float, float, float]


def _choice(value, allowed: set[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_screening(path: Path, out_dir: Path, settings: Settings, meta: dict, *,
                  dem_fetcher: Callable[[Bbox, Settings], DemGrid] | None = None) -> dict:
    """Validate + analyse + draw. Writes into out_dir:
         1_site_layout.png, 2_elevation.png, 3_slope_classes.png, 4_profiles.png,
         result.json, summary.md
       Returns the result dict (same content as result.json). `meta` keys:
         report_id, generated_at (ISO UTC), site_label, scheme, stage, input_filename.
       Raises ScreeningError on user-fixable problems and on DEM unavailability
       (message must say the DEM service could not be reached, never fabricate elevations).

       dem_fetcher (keyword-only): optional callable ``(bbox, settings) -> DemGrid`` used
       instead of the provider selected by ``settings.dem_provider``; bbox is
       (min_lon, min_lat, max_lon, max_lat) of the buffered analysis frame. Tests use it
       to inject synthetic terrain.
    """
    path, out_dir = Path(path), Path(out_dir)
    meta = dict(meta or {})
    input_filename = str(meta.get("input_filename") or path.name)
    site = validate_upload(path, settings, input_filename)

    bbox = analysis.analysis_bbox(site)
    dem = (dem_fetcher or fetch_dem)(bbox, settings)
    an = analysis.analyse(site, dem, settings)

    result: dict = {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "report_id": str(meta.get("report_id") or ""),
            "generated_at": str(meta.get("generated_at")
                                or datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
            "site_label": meta.get("site_label") or None,
            "scheme": _choice(meta.get("scheme"), SCHEMES),
            "stage": _choice(meta.get("stage"), STAGES),
            "input_filename": site.source_filename,
            "input_sha256": _sha256(path),
        },
    }
    sections = analysis.result_sections(an)
    state, district = boundaries.lookup(*an.centroid)
    sections["location"].update(state=state, district=district,
                                boundary_attribution=boundaries.BOUNDARY_ATTRIBUTION)
    result.update(sections)
    result["flags"] = flags.build_flags(result)
    result["followups"] = flags.build_followups(result)
    result["caveats"] = flags.build_caveats(result, site.repaired)
    result["figures"] = flags.figure_entries(result)

    out_dir.mkdir(parents=True, exist_ok=True)
    figures.draw_all(an, out_dir, flags.figure_stamp(result["dem"]))
    # allow_nan=False guarantees the file is strict JSON (no NaN/Infinity).
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (out_dir / "summary.md").write_text(render_summary_md(result), encoding="utf-8")
    log.info("screening %s: %d sites, %.1f ha", result["meta"]["report_id"],
             len(result["sites"]), result["totals"]["total_area_ha"] or 0.0)
    return result


# ---------------------------------------------------------------------------
# summary.md (human-readable mirror of result.json)
# ---------------------------------------------------------------------------
_MD_SPECIAL = "\\`*_[]<>|#"


def _md(text) -> str:
    """Escape untrusted text for markdown (names come from the uploaded file)."""
    return "".join("\\" + c if c in _MD_SPECIAL else c for c in str(text))


def _v(x, unit: str = "", nd: int = 1) -> str:
    """Format a result number (ints as-is, floats to nd decimals); None -> n/a."""
    if x is None:
        return "n/a"
    if isinstance(x, int) and not isinstance(x, bool):
        return f"{x:,}{unit}"
    return f"{x:,.{nd}f}{unit}"


def render_summary_md(result: dict) -> str:
    m, d, loc, tot = result["meta"], result["dem"], result["location"], result["totals"]
    lines = ["# Terrain screening summary", ""]
    if m.get("site_label"):
        lines += [f"**Site:** {_md(m['site_label'])}", ""]
    lines += [
        f"- Report: {_md(m['report_id'] or 'n/a')} · generated {_md(m['generated_at'])}",
        f"- Input file: {_md(m['input_filename'])} (sha256 `{m['input_sha256'][:16]}…`)",
        f"- Scheme: {_md(m['scheme'] or 'not stated')} · stage: {_md(m['stage'] or 'not stated')}",
        f"- Location: {_md(loc['district'] or 'n/a')}, {_md(loc['state'] or 'n/a')} "
        f"({_v(loc['centroid_lat'], nd=5)}°N, {_v(loc['centroid_lon'], nd=5)}°E) · {loc['utm_epsg']}",
        f"- DEM: {_md(d['name'])} — {_md(d['model_type'])}; epoch {_md(d['epoch'])}; "
        f"vertical datum {_md(d['vertical_datum'])}; nominal {d['nominal_resolution_m']} m, "
        f"analysed at {_v(d['grid_spacing_m'], ' m')} ({d['cells_analysed']:,} cells, "
        f"{_v(d['nodata_pct'], '%')} without data)",
        "",
        "## Totals",
        "",
        f"- {tot['polygon_count']} site polygon(s), total {_v(tot['total_area_ha'], ' ha', 2)}",
        f"- {tot['line_count']} route(s), total {_v(tot['total_line_km'], ' km', 2)}",
        f"- {tot['point_count']} point(s)",
        "- KPKT split (all sites, overlaps counted once): " + ", ".join(
            f"Class {k} {_v(v, '%')}" for k, v in result["kpkt_overall_pct"].items()),
        f"- Contour interval: {_v(result['contour_interval_m'], ' m')}",
        "",
    ]
    if result["sites"]:
        lines += ["## Sites", "",
                  "| Site | Area (ha) | Elevation min–max (mean) m | Relief m | "
                  "Slope mean / p90 / max ° | KPKT I / II / III / IV % | Cells |",
                  "|---|---:|---|---:|---|---|---:|"]
        for s in result["sites"]:
            k = s["kpkt_pct"]
            lines.append(
                f"| {_md(s['name'])} | {_v(s['area_ha'], nd=2)} | {_v(s['elev_min_m'])}–"
                f"{_v(s['elev_max_m'])} ({_v(s['elev_mean_m'])}) | {_v(s['relief_m'])} | "
                f"{_v(s['slope_mean_deg'])} / {_v(s['slope_p90_deg'])} / {_v(s['slope_max_deg'])} | "
                f"{_v(k['I'])} / {_v(k['II'])} / {_v(k['III'])} / {_v(k['IV'])} | {s['cells']} |")
        lines += ["", "Slope bins (% of site area):", "",
                  "| Site | " + " | ".join(_md(b) for b in result["sites"][0]["slope_bins_pct"]) + " |",
                  "|---|" + "---:|" * len(result["sites"][0]["slope_bins_pct"])]
        for s in result["sites"]:
            lines.append(f"| {_md(s['name'])} | "
                         + " | ".join(_v(v) for v in s["slope_bins_pct"].values()) + " |")
        lines.append("")
    if result["routes"]:
        lines += ["## Routes", "",
                  "| Route | Length km | Elevation min–max m | Total ascent m | Max grade % |",
                  "|---|---:|---|---:|---:|"]
        for r in result["routes"]:
            lines.append(f"| {_md(r['name'])} | {_v(r['length_km'], nd=2)} | {_v(r['elev_min_m'])}–"
                         f"{_v(r['elev_max_m'])} | {_v(r['total_ascent_m'])} | {_v(r['max_grade_pct'])} |")
        lines.append("")
    if result["points"]:
        lines += ["## Points", "", "| Point | Lat | Lon | Elevation m |", "|---|---:|---:|---:|"]
        for p in result["points"]:
            lines.append(f"| {_md(p['name'])} | {_v(p['lat'], nd=5)} | {_v(p['lon'], nd=5)} | "
                         f"{_v(p['elev_m'])} |")
        lines.append("")
    lines += ["## Flags", ""]
    for f in result["flags"]:
        src = f" *(Source: {_md(f['source'])})*" if f.get("source") else ""
        lines.append(f"- **{f['level'].upper()} — {_md(f['title'])}.** {_md(f['detail'])}{src}")
    lines += ["", "## Recommended follow-up studies", ""]
    lines += [f"{i}. **{_md(f['title'])}** — {_md(f['detail'])}"
              for i, f in enumerate(result["followups"], 1)]
    lines += ["", "## Caveats", ""]
    lines += [f"- {_md(c)}" for c in result["caveats"]]
    lines += ["", "## Figures", ""]
    for f in result["figures"]:
        lines += [f"### {_md(f['title'])}", "", f"![{_md(f['title'])}]({f['file']})", "",
                  _md(f["caption"]), ""]
    lines += ["---", "", f"{_md(d['attribution'])}  "]
    if d.get("disclaimer"):
        lines.append(f"{_md(d['disclaimer'])}  ")
    lines += [f"{_md(loc['boundary_attribution'])}", ""]
    return "\n".join(lines)
