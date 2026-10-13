"""Renderer-neutral report content.

``build_content(result, out_dir, settings)`` turns a result dict (result.json,
schema_version 1) into document metadata plus an ordered list of blocks. The PDF and
DOCX renderers walk the same list, so both formats always say exactly the same thing.

Wording rules: everything that interprets the terrain (flags, follow-ups, caveats and
figure captions) is copied verbatim from the result, where app.terrain.flags wrote it.
This module only adds report structure text: the cover, "About this report", table
headings and definitions, data sources, the disclaimer and the call to action.

Block text is plain, unescaped text. Site and route names come from the visitor's KML
and the site label from the upload form, so every renderer must escape for its own
format. Characters that are illegal in XML are already stripped here.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Union
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..config import Settings

BRAND = "EcoEnergy Consultancy"
REPORT_TITLE = "Desktop Terrain Screening"
SCREENING_LABEL = "Screening grade — not a survey"
ENGINE_CREDIT = "Analysis: EcoEnergy terrain screening engine v1"
CTA_TITLE = "Book a free 30-minute scheme-fit consult"
CTA_LINK_TEXT = "Book your consult"
DASH = "—"
MAX_NAME_CHARS = 120          # longer site/route names are shortened with an ellipsis
MAX_TEXT_CHARS = 4000         # hard cap for any single piece of text from the result

# Malaysia has no daylight saving; a fixed offset avoids needing tzdata on Windows hosts.
MYT = timezone(timedelta(hours=8), "MYT")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")

# Same vocabulary as app.main.SCHEMES / STAGES (duplicated so rendering never imports the web app).
SCHEME_LABELS = {
    "lss": "Large Scale Solar (LSS)",
    "cress": "CRESS",
    "fpv": "Floating solar (FPV)",
    "rooftop": "Rooftop / self-consumption",
    "other": "Other",
}
STAGE_LABELS = {
    "exploring": "Exploring options",
    "land_secured": "Land secured / under negotiation",
    "bidding": "Preparing a bid or submission",
    "other": "Other",
}

# Labels the engine's boundary attribution may start with (the last one is the default title).
BOUNDARY_LABELS = ("State and district boundaries:", "Administrative boundaries:")

LEVELS = ("warning", "caution", "info")
LEVEL_LABELS = {"warning": "Warning", "caution": "Caution", "info": "Information"}
KPKT_CLASSES = ("I", "II", "III", "IV")
SLOPE_BINS = ("0-2", "2-5", "5-10", "10-15", "15-25", "25-35", ">35")

# XML 1.0 forbids C0 controls (except tab/newline/CR), lone surrogates and U+FFFE/U+FFFF;
# python-docx refuses them and ReportLab's parser chokes on some.
_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff￾￿]")


# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Cover:
    brand: str
    title: str
    subtitle: str                              # site label, or the input filename
    location: str                              # "District, State"
    label: str                                 # screening-grade label
    details: tuple[tuple[str, str], ...]       # key/value rows under the cover band


@dataclass(frozen=True)
class Heading:
    text: str
    level: int = 1                             # 1 = section, 2 = subsection
    # Keep this whole section (up to the next level-1 heading or page break) on one page
    # when it fits; renderers that cannot express this may ignore it.
    keep_section: bool = False


@dataclass(frozen=True)
class Paragraph:
    text: str
    style: str = "body"                        # body | lead | note


@dataclass(frozen=True)
class ListItem:
    text: str
    title: str | None = None                   # rendered bold ahead of the text


@dataclass(frozen=True)
class BulletList:
    items: tuple[ListItem, ...]
    numbered: bool = False


@dataclass(frozen=True)
class KeyValueTable:
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DataTable:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    align: tuple[str, ...]                     # "left" | "right" per column
    widths: tuple[float, ...]                  # relative column widths
    # Optional header row above `columns`: (label, span) pairs covering every column.
    # A None label means those columns have no group, so their header spans both rows.
    groups: tuple[tuple[str | None, int], ...] = ()
    total: tuple[str, ...] | None = None       # emphasised summary row
    note: str | None = None                    # small print under the table


@dataclass(frozen=True)
class Callout:
    level: str                                 # info | caution | warning
    title: str
    text: str
    source: str | None = None

    @property
    def label(self) -> str:
        return LEVEL_LABELS[self.level]


@dataclass(frozen=True)
class Figure:
    number: int
    title: str
    caption: str
    path: Path | None                          # None when the PNG is missing or unreadable
    size_px: tuple[int, int] | None = None     # (width, height), for aspect ratio


@dataclass(frozen=True)
class PageBreak:
    pass


@dataclass(frozen=True)
class Cta:
    title: str
    text: str
    link_text: str
    base_url: str

    def url_for(self, medium: str) -> str:
        return tracked_url(self.base_url, medium)

    @property
    def display_url(self) -> str:
        """The link as printed for readers of a paper copy (no scheme, no tracking)."""
        parts = urlsplit(self.base_url)
        return (parts.netloc + parts.path) or self.base_url


Block = Union[Cover, Heading, Paragraph, BulletList, KeyValueTable, DataTable, Callout,
              Figure, PageBreak, Cta]


@dataclass(frozen=True)
class DocInfo:
    title: str                                 # document metadata title
    subject: str
    author: str
    keywords: tuple[str, ...]
    report_id: str
    short_id: str                              # report_id[:8], used in page headers
    generated_at: datetime | None              # UTC
    header_brand: str                          # running header, left, bold ...
    header_title: str                          # ... followed by " · " and this
    header_right: str                          # renderers append " · page N of M"
    footer: str


@dataclass(frozen=True)
class ReportContent:
    info: DocInfo
    blocks: list[Block] = field(default_factory=list)


# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------
def clean(value, limit: int = MAX_TEXT_CHARS) -> str:
    """Plain text safe for any renderer: str(), XML-illegal characters removed, capped."""
    if value is None:
        return ""
    s = _ILLEGAL_XML.sub("", str(value)).replace("\r\n", "\n").replace("\r", "\n")
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


def name_text(value) -> str:
    """A feature name for a table cell: one line, whitespace collapsed, length capped."""
    s = " ".join(clean(value, 10 * MAX_NAME_CHARS).split())
    if len(s) > MAX_NAME_CHARS:
        s = s[: MAX_NAME_CHARS - 1].rstrip() + "…"
    return s or DASH


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def num(x, nd: int = 1, unit: str = "") -> str:
    """Number with thousands separators and `nd` decimals, or an em dash when unknown."""
    return f"{x:,.{nd}f}{unit}" if _ok(x) else DASH


def num_range(lo, hi, nd: int = 1, unit: str = "") -> str:
    if not (_ok(lo) or _ok(hi)):
        return DASH
    return f"{num(lo, nd)}–{num(hi, nd)}{unit}"


def plural(n: int, word: str, words: str | None = None) -> str:
    return f"{n} {word if n == 1 else (words or word + 's')}"


def parse_generated(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def format_generated(value) -> str:
    """ISO timestamp -> "13 October 2026, 16:00 MYT" (Asia/Kuala_Lumpur, locale independent)."""
    dt = parse_generated(value)
    if dt is None:
        return clean(value, 64) or DASH
    local = dt.astimezone(MYT)
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year}, {local:%H:%M} MYT"


def tracked_url(base: str, medium: str) -> str:
    """Append utm_source=terrain_tool&utm_medium=<medium>, keeping any existing query."""
    parts = urlsplit(base)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in ("utm_source", "utm_medium")]
    query += [("utm_source", "terrain_tool"), ("utm_medium", medium)]
    return urlunsplit(parts._replace(query=urlencode(query)))


def bin_label(key: str) -> str:
    """Slope-bin key from result.json ("0-2", ">35") -> column label ("0–2°", ">35°")."""
    k = clean(key, 20)
    return (k.replace("-", "–") + "°") if k else DASH


def _datum(dem: dict) -> str:
    """Vertical datum name, or "" when the DEM does not state a usable one."""
    d = clean(dem.get("vertical_datum"), 60).strip()
    return "" if d.lower() in {"", "none", "unknown", "n/a"} else d


def _coord(lat, lon) -> str:
    if not (_ok(lat) and _ok(lon)):
        return DASH
    return f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.5f}° {'E' if lon >= 0 else 'W'}"


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------
def _location_text(loc: dict) -> str:
    parts = [name_text(loc.get(k)) for k in ("district", "state") if loc.get(k)]
    return ", ".join(parts) if parts else "State and district not identified"


def _label(labels: dict[str, str], value) -> str:
    return labels.get(value, "Not stated") if isinstance(value, str) else "Not stated"


def _cover(result: dict) -> Cover:
    meta, loc = result.get("meta") or {}, result.get("location") or {}
    label = " ".join(clean(meta.get("site_label"), 200).split())
    filename = clean(meta.get("input_filename"), 200)
    details = [
        ("Report ID", clean(meta.get("report_id"), 64) or DASH),
        ("Generated", format_generated(meta.get("generated_at"))),
    ]
    if label:
        details.append(("Site file", filename or DASH))
    details += [
        ("Scheme", _label(SCHEME_LABELS, meta.get("scheme"))),
        ("Project stage", _label(STAGE_LABELS, meta.get("stage"))),
        ("Centroid", _coord(loc.get("centroid_lat"), loc.get("centroid_lon"))),
    ]
    return Cover(brand=BRAND, title=REPORT_TITLE, subtitle=label or filename or "Uploaded site",
                 location=_location_text(loc), label=SCREENING_LABEL, details=tuple(details))


def _about(result: dict) -> list[Block]:
    dem = result.get("dem") or {}
    meta = result.get("meta") or {}
    filename = clean(meta.get("input_filename"), 200) or "your uploaded file"
    dem_name = clean(dem.get("name"), 200) or "an open global elevation model"
    return [
        Heading("About this report", 1),
        Paragraph(
            f"This desktop screening summarises the terrain inside the boundaries supplied in "
            f"{filename}, using the {dem_name}. It is meant for comparing candidate sites at an "
            "early stage and for deciding which surveys and studies to commission next.", "lead"),
        Paragraph(
            "It reports the area, elevation and slope of each site, the share of each site in "
            "the KPKT hill-land slope classes, rule-based findings and recommended follow-up "
            "studies. Every finding is generated automatically from the elevation data by fixed "
            "rules; nobody has visited the site."),
        Paragraph(
            "Read the caveats and the disclaimer at the end of the report before relying on any "
            "figure in it.", "note"),
    ]


def _site_values(sites: list[dict], key: str) -> list[float]:
    return [s[key] for s in sites if _ok(s.get(key))]


def _at_a_glance(result: dict) -> list[Block]:
    sites, routes = result.get("sites") or [], result.get("routes") or []
    points = result.get("points") or []
    totals, dem = result.get("totals") or {}, result.get("dem") or {}
    loc, flags = result.get("location") or {}, result.get("flags") or []

    features = [plural(len(sites), "site")]
    if routes:
        features.append(f"{plural(len(routes), 'route')} ({num(totals.get('total_line_km'), 2, ' km')})")
    features.append(plural(len(points), "point"))

    lows = _site_values(sites, "elev_min_m") or _site_values(routes, "elev_min_m") \
        or _site_values(points, "elev_m")
    highs = _site_values(sites, "elev_max_m") or _site_values(routes, "elev_max_m") \
        or _site_values(points, "elev_m")
    datum = _datum(dem)
    elev = num_range(min(lows) if lows else None, max(highs) if highs else None, 1, " m")
    if elev != DASH and datum:
        elev += f" ({datum})"

    steepest = max((s for s in sites if _ok(s.get("slope_max_deg"))),
                   key=lambda s: s["slope_max_deg"], default=None)
    max_slope = DASH
    if steepest:
        max_slope = (f"{num(steepest['slope_max_deg'], 1, '°')} "
                     f"(in “{name_text(steepest.get('name'))}”)")

    kpkt = result.get("kpkt_overall_pct") or {}
    kpkt_text = (" · ".join(f"Class {c} {num(kpkt.get(c), 1, '%')}" for c in KPKT_CLASSES)
                 if any(_ok(kpkt.get(c)) for c in KPKT_CLASSES) else DASH)

    counts = {lvl: sum(1 for f in flags if _level(f) == lvl) for lvl in LEVELS}
    findings = " · ".join([plural(counts["warning"], "warning"), plural(counts["caution"], "caution"),
                           f"{counts['info']} for information"])

    dem_parts = [clean(dem.get("name"), 120) or DASH]
    if dem.get("model_type"):
        dem_parts.append(clean(dem.get("model_type"), 160))
    res = []
    if _ok(dem.get("nominal_resolution_m")):
        res.append(f"{num(dem['nominal_resolution_m'], 0)} m nominal")
    if _ok(dem.get("grid_spacing_m")):
        res.append(f"analysed at {num(dem['grid_spacing_m'], 1)} m")
    if res:
        dem_parts.append(", ".join(res))

    rows = (
        ("Location", _location_text(loc)),
        ("Total site area", num(totals.get("total_area_ha"), 2, " ha")),
        ("Features analysed", " · ".join(features)),
        ("Elevation range", elev),
        ("Overall KPKT split", kpkt_text),
        ("Maximum slope", max_slope),
        ("Findings", findings),
        ("Elevation model (DEM)", " · ".join(dem_parts)),
    )
    return [Heading("At a glance", 1), KeyValueTable(rows)]


def _level(flag: dict) -> str:
    lvl = flag.get("level")
    return lvl if lvl in LEVELS else "info"


def _findings(result: dict) -> list[Block]:
    flags = result.get("flags") or []
    out: list[Block] = [Heading("Findings", 1)]
    if not flags:
        out.append(Paragraph("No findings were raised for this screening."))
        return out
    out.append(Paragraph(
        "Each finding below is computed by fixed rules from the elevation data and is listed "
        "most severe first: warnings, then cautions, then information.", "note"))
    for f in flags:
        source = clean(f.get("source"), 400) or None
        out.append(Callout(level=_level(f), title=clean(f.get("title"), 300) or DASH,
                           text=clean(f.get("detail")), source=source))
    return out


def _sites_table(result: dict) -> list[Block]:
    sites = result.get("sites") or []
    dem = result.get("dem") or {}
    out: list[Block] = [Heading("Sites", 2)]
    if not sites:
        out.append(Paragraph("No site polygons were supplied in the file."))
        return out
    rows = []
    for s in sites:
        k = s.get("kpkt_pct") or {}
        rows.append((
            name_text(s.get("name")),
            num(s.get("area_ha"), 2),
            num_range(s.get("elev_min_m"), s.get("elev_max_m")),
            num(s.get("relief_m")),
            num(s.get("slope_mean_deg")), num(s.get("slope_p90_deg")), num(s.get("slope_max_deg")),
            *(num(k.get(c)) for c in KPKT_CLASSES),
        ))
    total = None
    if len(sites) > 1:
        lows, highs = _site_values(sites, "elev_min_m"), _site_values(sites, "elev_max_m")
        maxes = _site_values(sites, "slope_max_deg")
        kpkt = result.get("kpkt_overall_pct") or {}
        total = (
            "All sites",
            num((result.get("totals") or {}).get("total_area_ha"), 2),
            num_range(min(lows) if lows else None, max(highs) if highs else None),
            num(max(highs) - min(lows)) if lows and highs else DASH,
            DASH, DASH, num(max(maxes)) if maxes else DASH,
            *(num(kpkt.get(c)) for c in KPKT_CLASSES),
        )
    datum = _datum(dem)
    datum_text = f" above {datum}" if datum else ""
    out.append(DataTable(
        columns=("Site", "Area (ha)", "Elevation min–max (m)", "Relief (m)",
                 "Mean", "P90", "Max", "I", "II", "III", "IV"),
        rows=tuple(rows),
        align=("left",) + ("right",) * 10,
        widths=(3.4, 1.3, 1.9, 1.15, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95),
        groups=((None, 4), ("Slope (°)", 3), ("KPKT class (% of site area)", 4)),
        total=total,
        note=(f"Elevations are DEM surface heights in metres{datum_text}. P90 is the "
              "90th-percentile slope: nine-tenths of the site area is at or below it. KPKT classes: "
              "I below 15°, II 15–25°, III 25–35°, IV 35° and steeper."
              + (" The all-sites KPKT split is area-weighted." if total else "")),
    ))
    return out


def _slope_table(result: dict) -> list[Block]:
    sites = result.get("sites") or []
    if not sites:
        return []
    keys = list(SLOPE_BINS)
    for s in sites:                            # keep any bin the engine adds, in its own order
        for key in (s.get("slope_bins_pct") or {}):
            if key not in keys:
                keys.append(key)
    rows = tuple((name_text(s.get("name")),
                  *(num((s.get("slope_bins_pct") or {}).get(key)) for key in keys)) for s in sites)
    return [
        Heading("Slope distribution", 2),
        DataTable(
            columns=("Site", *(bin_label(k) for k in keys)),
            rows=rows,
            align=("left",) + ("right",) * len(keys),
            widths=(3.4,) + (1.0,) * len(keys),
            groups=((None, 1), ("Share of site area in each slope band (%)", len(keys))),
        ),
    ]


def _routes_table(result: dict) -> list[Block]:
    routes = result.get("routes") or []
    if not routes:
        return []
    rows = tuple((name_text(r.get("name")), num(r.get("length_km"), 2),
                  num_range(r.get("elev_min_m"), r.get("elev_max_m")),
                  num(r.get("total_ascent_m")), num(r.get("max_grade_pct"))) for r in routes)
    return [
        Heading("Routes", 2),
        DataTable(columns=("Route", "Length (km)", "Elevation min–max (m)", "Total ascent (m)",
                           "Max grade (%)"),
                  rows=rows, align=("left", "right", "right", "right", "right"),
                  widths=(3.4, 1.3, 1.9, 1.5, 1.5)),
    ]


def _points_table(result: dict) -> list[Block]:
    points = result.get("points") or []
    if not points:
        return []
    rows = tuple((name_text(p.get("name")), num(p.get("lat"), 5), num(p.get("lon"), 5),
                  num(p.get("elev_m"))) for p in points)
    return [
        Heading("Points", 2),
        DataTable(columns=("Point", "Latitude (°)", "Longitude (°)", "Elevation (m)"),
                  rows=rows, align=("left", "right", "right", "right"),
                  widths=(3.4, 1.6, 1.6, 1.5)),
    ]


def _figure_file(out_dir: Path, name) -> tuple[Path | None, tuple[int, int] | None]:
    """Resolve a figure entry to a readable PNG inside out_dir (never outside it)."""
    if not isinstance(name, str) or not name or Path(name).name != name:
        return None, None
    path = out_dir / name
    if not path.is_file():
        return None, None
    try:
        from PIL import Image                  # Pillow ships with matplotlib and ReportLab
        with Image.open(path) as im:
            w, h = im.size
    except Exception:                          # unreadable image: render the placeholder instead
        return None, None
    if w <= 0 or h <= 0:
        return None, None
    return path, (int(w), int(h))


def _figures(result: dict, out_dir: Path) -> list[Block]:
    out: list[Block] = []
    for i, f in enumerate(result.get("figures") or [], 1):
        path, size = _figure_file(out_dir, f.get("file"))
        title = clean(f.get("title"), 200) or f"Figure {i}"
        out.append(PageBreak())
        if i == 1:
            out.append(Heading("Figures", 1))
        out += [Heading(f"Figure {i}. {title}", 2),
                Figure(number=i, title=title, caption=clean(f.get("caption")), path=path, size_px=size)]
    return out


def _followups(result: dict) -> list[Block]:
    items = tuple(ListItem(title=clean(f.get("title"), 300) or None, text=clean(f.get("detail")))
                  for f in result.get("followups") or [])
    out: list[Block] = [Heading("Recommended follow-up studies", 1)]
    if items:
        out.append(BulletList(items, numbered=True))
    else:
        out.append(Paragraph("No follow-up studies were listed for this screening."))
    return out


def _caveats(result: dict) -> list[Block]:
    items = tuple(ListItem(clean(c)) for c in result.get("caveats") or [] if clean(c))
    out: list[Block] = [Heading("Caveats and limitations", 1)]
    if items:
        out.append(BulletList(items))
    return out


def _sources(result: dict) -> list[Block]:
    dem, loc, meta = result.get("dem") or {}, result.get("location") or {}, result.get("meta") or {}
    items: list[ListItem] = []
    if dem.get("attribution"):
        items.append(ListItem(clean(dem["attribution"], 600), title="Elevation data:"))
    if dem.get("disclaimer"):
        # Licence notice the DEM provider requires in a legal notice (Copernicus Art. 6(c)).
        items.append(ListItem(clean(dem["disclaimer"], 600), title="Elevation data notice:"))
    model = [clean(dem.get("name"), 200) or DASH]
    for key, fmt in (("model_type", "{}"), ("epoch", "acquired {}"),
                     ("vertical_datum", "vertical datum {}")):
        if dem.get(key):
            model.append(fmt.format(clean(dem[key], 200)))
    if _ok(dem.get("nominal_resolution_m")):
        model.append(f"{num(dem['nominal_resolution_m'], 0)} m nominal resolution, analysed at "
                     f"{num(dem.get('grid_spacing_m'), 1)} m over {num(dem.get('cells_analysed'), 0)} "
                     f"cells ({num(dem.get('nodata_pct'), 1)}% without data)")
    items.append(ListItem("; ".join(model) + ".", title="Elevation model:"))
    boundaries = clean(loc.get("boundary_attribution"), 600)
    if boundaries:
        # The engine's attribution starts with its own label, e.g. "State and district
        # boundaries:"; use it as the item title instead of repeating it.
        prefix = next((p for p in BOUNDARY_LABELS if boundaries.startswith(p)), BOUNDARY_LABELS[-1])
        items.append(ListItem(boundaries.removeprefix(prefix).strip(), title=prefix))
    if loc.get("utm_epsg"):
        items.append(ListItem(f"areas, lengths and slopes are computed on a local UTM grid "
                              f"({clean(loc['utm_epsg'], 40)}, WGS 84).", title="Projection:"))
    sha = clean(meta.get("input_sha256"), 64)
    geometry = f"{clean(meta.get('input_filename'), 200) or 'uploaded file'}, used as supplied"
    if sha:
        geometry += f" (SHA-256 {sha[:16]}…)"
    items.append(ListItem(geometry + ".", title="Site geometry:"))
    credit_title, credit_text = ENGINE_CREDIT.split(": ", 1)
    items.append(ListItem(credit_text, title=credit_title + ":"))
    return [Heading("Data sources and attribution", 1), BulletList(tuple(items))]


def _disclaimer() -> list[Block]:
    return [
        Heading("Disclaimer", 1),
        Paragraph(
            "This report is a desktop screening produced automatically from open global elevation "
            "data, for early-stage site comparison only. It is not a topographic survey, not "
            "engineering design and not for submission to any authority. A topographic survey by "
            "a licensed land surveyor (Licensed Land Surveyors Act 1958) is required for design. "
            f"{BRAND} accepts no liability for decisions made solely on the basis of this "
            "screening."),
    ]


def _cta(settings: Settings) -> list[Block]:
    return [Heading("Next step", 1), Cta(
        title=CTA_TITLE,
        text=("Walk through these results with an EcoEnergy consultant. In 30 minutes we will go "
              "over the findings, check which scheme the site fits, and agree which surveys and "
              "studies to commission first."),
        link_text=CTA_LINK_TEXT,
        base_url=settings.consult_url,
    )]


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def doc_info(result: dict) -> DocInfo:
    meta, loc = result.get("meta") or {}, result.get("location") or {}
    report_id = clean(meta.get("report_id"), 64)
    subject_site = " ".join(clean(meta.get("site_label"), 200).split()) \
        or clean(meta.get("input_filename"), 200) or "uploaded site"
    keywords = ["terrain screening", "slope", "KPKT", "elevation", "solar", "Malaysia"]
    keywords += [clean(loc[k], 80) for k in ("state", "district") if loc.get(k)]
    return DocInfo(
        title=f"{REPORT_TITLE} — {subject_site}",
        subject=f"Desktop terrain screening report {report_id}".strip(),
        author=BRAND,
        keywords=tuple(keywords),
        report_id=report_id,
        short_id=report_id[:8] or DASH,
        generated_at=parse_generated(meta.get("generated_at")),
        header_brand=BRAND,
        header_title=REPORT_TITLE,
        header_right=f"Report {report_id[:8] or DASH}",
        footer=SCREENING_LABEL,
    )


def build_content(result: dict, out_dir: Path, settings: Settings) -> ReportContent:
    """Ordered, renderer-neutral report content for `result` (figures resolved in out_dir)."""
    out_dir = Path(out_dir)
    blocks: list[Block] = [
        _cover(result), *_about(result), PageBreak(),
        *_at_a_glance(result), *_findings(result),
        # statistics follow the findings, moving to a fresh page only when they do not fit
        Heading("Site statistics", 1, keep_section=True),
        *_sites_table(result), *_slope_table(result), *_routes_table(result), *_points_table(result),
        *_figures(result, out_dir), PageBreak(),
        *_followups(result), *_caveats(result), *_sources(result), *_disclaimer(), *_cta(settings),
    ]
    return ReportContent(info=doc_info(result), blocks=blocks)
