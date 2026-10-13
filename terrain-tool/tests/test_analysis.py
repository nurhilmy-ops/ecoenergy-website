"""Terrain engine tests with synthetic DEMs (no network), plus one opt-in network test."""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine_helpers import (FIXTURES, GEOD, SYNTH_INFO, function_fetcher, kml_doc,  # noqa: E402
                            line_pm, make_settings, offset, plane_fetcher, point_pm,
                            polygon_pm, rect, result_with, route_result, site_result, write)

from app.terrain import ScreeningError, render_summary_md, run_screening, validate_upload  # noqa: E402
from app.terrain import analysis, boundaries, dem, flags  # noqa: E402
from app.terrain.dem import DemGrid  # noqa: E402

LON, LAT = 101.5, 3.5
FIGURE_FILES = ["1_site_layout.png", "2_elevation.png", "3_slope_classes.png", "4_profiles.png"]

# result.json contract (docs/ARCHITECTURE.md, schema_version 1)
TOP_KEYS = {"schema_version", "meta", "dem", "location", "totals", "sites", "kpkt_overall_pct",
            "routes", "points", "contour_interval_m", "flags", "followups", "caveats", "figures"}
META_KEYS = {"report_id", "generated_at", "site_label", "scheme", "stage", "input_filename",
             "input_sha256"}
DEM_KEYS = {"provider", "name", "model_type", "epoch", "vertical_datum", "nominal_resolution_m",
            "grid_spacing_m", "cells_analysed", "nodata_pct", "attribution", "disclaimer",
            "sends_coordinates_to_third_party"}
LOCATION_KEYS = {"centroid_lon", "centroid_lat", "state", "district", "utm_epsg",
                 "boundary_attribution"}
TOTALS_KEYS = {"polygon_count", "line_count", "point_count", "total_area_ha", "total_line_km",
               "steeper_than_grade_pct"}
SITE_KEYS = {"name", "area_ha", "perimeter_m", "centroid", "elev_min_m", "elev_max_m",
             "elev_mean_m", "relief_m", "slope_mean_deg", "slope_p90_deg", "slope_max_deg",
             "kpkt_pct", "slope_bins_pct", "steeper_than_grade_pct", "cells"}
KPKT_KEYS = {"I", "II", "III", "IV"}
BIN_KEYS = {"0-2", "2-5", "5-10", "10-15", "15-25", "25-35", ">35"}
ROUTE_KEYS = {"name", "length_km", "elev_min_m", "elev_max_m", "total_ascent_m", "max_grade_pct",
              "max_slope_deg", "length_on_35deg_m"}
POINT_KEYS = {"name", "lon", "lat", "elev_m"}
FLAG_KEYS = {"level", "code", "title", "detail", "source"}
FOLLOWUP_KEYS = {"title", "detail"}
FIGURE_KEYS = {"file", "title", "caption"}


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


def screen(tmp_path, body, fetcher, settings=None, scheme="lss", **meta):
    tmp_path.mkdir(parents=True, exist_ok=True)
    src = write(tmp_path, "site.kml", kml_doc(body))
    out = tmp_path / "out"
    m = {"report_id": "r1", "generated_at": "2026-10-13T08:00:00+00:00", "site_label": None,
         "scheme": scheme, "stage": None, "input_filename": "site.kml", **meta}
    return run_screening(src, out, settings or make_settings(tmp_path), m, dem_fetcher=fetcher), out


def codes(result) -> list[str]:
    return [f["code"] for f in result["flags"]]


# ---------------------------------------------------------------------------
# slope and KPKT classes inside polygons
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("slope_deg, expected_class", [(5.0, "I"), (20.0, "II"), (30.0, "III"), (40.0, "IV")])
def test_plane_slope_gives_expected_kpkt_class(tmp_path, slope_deg, expected_class):
    body = polygon_pm("Plane", rect(LON, LAT, 450, 300))
    result, _ = screen(tmp_path, body, plane_fetcher(slope_deg))
    site = result["sites"][0]
    assert site["slope_mean_deg"] == pytest.approx(slope_deg, abs=0.2)
    assert site["slope_max_deg"] == pytest.approx(slope_deg, abs=0.2)
    assert site["kpkt_pct"][expected_class] == 100.0
    assert sum(v for k, v in site["kpkt_pct"].items() if k != expected_class) == 0.0
    assert result["kpkt_overall_pct"] == site["kpkt_pct"]
    assert site["cells"] > 100


def test_plane_running_north_also_measured(tmp_path):
    result, _ = screen(tmp_path, polygon_pm("N", rect(LON, LAT, 300, 450)),
                       plane_fetcher(12.0, direction="north"))
    assert result["sites"][0]["slope_mean_deg"] == pytest.approx(12.0, abs=0.2)
    assert result["sites"][0]["slope_bins_pct"]["10-15"] == 100.0


def test_buffer_cells_do_not_count_toward_site_kpkt(tmp_path):
    """Flat site inside a steep frame: the site must still be 100% Class I."""
    ring = rect(LON, LAT, 400, 300)
    lon0, lat0 = ring[0]
    lon1, lat1 = ring[2]
    margin = 3 / 3600                                  # 3 cells of flat ground around the site
    steep = math.tan(math.radians(40))

    def terrain(LONS, LATS, X, Y):
        inside = ((LONS > lon0 - margin) & (LONS < lon1 + margin)
                  & (LATS > lat0 - margin) & (LATS < lat1 + margin))
        return np.where(inside, 20.0, 20.0 + steep * np.abs(X) * 0.5 + steep * np.abs(Y) * 0.5)

    result, _ = screen(tmp_path, polygon_pm("Flat pad", ring), function_fetcher(terrain))
    site = result["sites"][0]
    assert site["kpkt_pct"] == {"I": 100.0, "II": 0.0, "III": 0.0, "IV": 0.0}
    assert site["slope_max_deg"] < 1.0
    assert not {"kpkt_class_ii", "kpkt_class_iii", "kpkt_class_iv"} & set(codes(result))
    assert "all_class_i" in codes(result)


def test_polygon_hole_is_excluded(tmp_path):
    outer = rect(LON, LAT, 600, 600)
    hole = rect(*offset(LON, LAT, 200, 200), 200, 200)
    h_lon0, h_lat0 = offset(LON, LAT, 260, 260)        # steep core 60 m inside the hole edge
    h_lon1, h_lat1 = offset(LON, LAT, 340, 340)
    steep = math.tan(math.radians(45))

    def terrain(LONS, LATS, X, Y):
        core = (LONS > h_lon0) & (LONS < h_lon1) & (LATS > h_lat0) & (LATS < h_lat1)
        return np.where(core, 30.0 + steep * X, 30.0)

    with_hole, _ = screen(tmp_path / "a", polygon_pm("Ring", outer, [hole]), function_fetcher(terrain),
                          settings=make_settings(tmp_path))
    no_hole, _ = screen(tmp_path / "b", polygon_pm("Solid", outer), function_fetcher(terrain),
                        settings=make_settings(tmp_path))
    s_hole, s_solid = with_hole["sites"][0], no_hole["sites"][0]
    assert s_hole["kpkt_pct"]["I"] == 100.0             # steep core sits in the hole
    assert s_solid["kpkt_pct"]["I"] < 100.0             # ... and would count without it
    assert s_solid["area_ha"] - s_hole["area_ha"] == pytest.approx(4.0, abs=0.05)
    assert s_hole["cells"] < s_solid["cells"]


def test_kpkt_overall_counts_cells_inside_any_site(tmp_path):
    big = rect(LON, LAT, 600, 400)                      # flat: 24 ha
    small = rect(*offset(LON, LAT, 1000, 0), 300, 200)  # 20°: 6 ha
    small_lon0 = small[0][0]
    t = math.tan(math.radians(20))

    def terrain(LONS, LATS, X, Y):
        return np.where(LONS > small_lon0 - 0.0015, 10.0 + t * X, 10.0)

    result, _ = screen(tmp_path, polygon_pm("Big", big) + polygon_pm("Small", small),
                       function_fetcher(terrain))
    s_big, s_small = result["sites"]
    # Every cell inside a site counts once; with disjoint sites that is close to area-weighting.
    assert result["kpkt_overall_pct"]["II"] == pytest.approx(
        100.0 * s_small["cells"] / (s_big["cells"] + s_small["cells"]), abs=0.05)
    expected_ii = 100.0 * s_small["area_ha"] / (s_big["area_ha"] + s_small["area_ha"])
    assert result["kpkt_overall_pct"]["II"] == pytest.approx(expected_ii, abs=1.0)
    assert result["totals"]["total_area_ha"] == pytest.approx(s_big["area_ha"] + s_small["area_ha"], abs=0.01)
    assert "kpkt_class_ii" in codes(result)


def test_nested_polygons_count_once_in_totals_and_capacity(tmp_path):
    """A lot boundary plus a phase block drawn inside it: the block must not add area, shift
    the overall KPKT split or inflate the capacity figures (GEO-2)."""
    t = math.tan(math.radians(20))
    fetcher = function_fetcher(lambda LONS, LATS, X, Y: np.where(X < 0, 10.0, 10.0 + t * X))
    lot = polygon_pm("Lot boundary", rect(LON, LAT, 1000, 1000))             # west half flat, east 20°
    block = polygon_pm("Phase 1 PV block", rect(*offset(LON, LAT, 50, 100), 400, 700))  # 28 ha, flat
    alone, _ = screen(tmp_path / "alone", lot, fetcher, settings=make_settings(tmp_path))
    nested, _ = screen(tmp_path / "nested", lot + block, fetcher, settings=make_settings(tmp_path))
    assert sum(s["area_ha"] for s in nested["sites"]) == pytest.approx(128.0, abs=0.5)
    assert nested["totals"]["total_area_ha"] == pytest.approx(alone["totals"]["total_area_ha"], abs=0.01)
    assert nested["kpkt_overall_pct"] == alone["kpkt_overall_pct"]
    assert nested["totals"]["steeper_than_grade_pct"] == alone["totals"]["steeper_than_grade_pct"]
    assert 40.0 < alone["kpkt_overall_pct"]["II"] < 60.0
    cap = {r: flag(x, "indicative_capacity")["detail"] for r, x in (("alone", alone), ("nested", nested))}
    assert cap["nested"] == cap["alone"]
    assert "128" not in cap["nested"]
    caption = {r: x["figures"][2]["caption"] for r, x in (("alone", alone), ("nested", nested))}
    assert caption["nested"] == caption["alone"]


# ---------------------------------------------------------------------------
# routes and points
# ---------------------------------------------------------------------------
def test_route_ascent_and_grade_on_ramp(tmp_path):
    grade = math.tan(math.radians(3.0))                 # 5.24 %
    west, east = (LON, LAT), offset(LON, LAT, 1000, 0)
    body = line_pm("Up", [west, east]) + line_pm("Down", [east, west]) + point_pm("P", east)
    result, _ = screen(tmp_path, body, plane_fetcher(3.0, base=100.0))
    up, down = result["routes"]
    assert up["length_km"] == pytest.approx(1.0, abs=0.01)
    assert up["total_ascent_m"] == pytest.approx(1000 * grade, abs=1.5)
    assert down["total_ascent_m"] == pytest.approx(0.0, abs=0.5)
    for r in (up, down):
        assert r["max_grade_pct"] == pytest.approx(100 * grade, abs=0.1)
        assert r["elev_max_m"] - r["elev_min_m"] == pytest.approx(1000 * grade, abs=1.5)
    # point on the ramp: interpolated elevation matches the plane
    p = result["points"][0]
    assert p["elev_m"] == pytest.approx(up["elev_max_m"], abs=0.2)
    assert "route_grade" in codes(result)


def test_max_grade_uses_90m_windows():
    d = np.arange(0, 301, 30.0)
    z = np.zeros_like(d)
    z[5] = 3.0                                           # single 3 m spike
    # A 30 m window would report 10 %; the >= 90 m window caps it at 3/90.
    assert analysis.max_grade_pct(d, z) == pytest.approx(100 * 3 / 90, abs=0.01)
    assert analysis.max_grade_pct(np.array([0.0, 50.0]), np.array([0.0, 5.0])) == pytest.approx(10.0)
    assert math.isnan(analysis.max_grade_pct(np.array([0.0, 50.0]), np.array([np.nan, 5.0])))


def test_total_ascent_smooths_noise():
    z = np.array([0, 1, 0, 1, 0, 1, 0, 1, 0, 1], dtype=float)
    raw = float(np.clip(np.diff(z), 0, None).sum())       # 5 m of pure noise
    assert analysis.total_ascent_m(z) < 0.5 * raw         # 3-sample average removes most of it
    assert analysis.total_ascent_m(np.linspace(0, 50, 20)) == pytest.approx(50.0)   # ramps survive


# ---------------------------------------------------------------------------
# outputs and schema
# ---------------------------------------------------------------------------
def _strict_json(path: Path):
    def bad(c):
        raise AssertionError(f"non-strict JSON constant {c}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=bad)


def test_outputs_written_and_schema_matches_contract(tmp_path):
    ring = rect(LON, LAT, 500, 400)
    body = (polygon_pm("Lot A", ring, [rect(*offset(LON, LAT, 100, 100), 80, 80)])
            + line_pm("Cable", [ring[1], offset(LON, LAT, 1500, 300)])
            + point_pm("PMU", offset(LON, LAT, 1500, 300)))
    hills = function_fetcher(lambda LONS, LATS, X, Y: 60 + 25 * np.sin(X / 300) * np.cos(Y / 250))
    result, out = screen(tmp_path, body, hills, site_label="North block", stage="exploring")

    for name in FIGURE_FILES:
        data = (out / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 20_000, name
    on_disk = _strict_json(out / "result.json")
    assert on_disk == result

    assert set(result) == TOP_KEYS
    assert result["schema_version"] == 1
    assert set(result["meta"]) == META_KEYS
    assert set(result["dem"]) == DEM_KEYS
    assert set(result["location"]) == LOCATION_KEYS
    assert set(result["totals"]) == TOTALS_KEYS
    for s in result["sites"]:
        assert set(s) == SITE_KEYS
        assert set(s["kpkt_pct"]) == KPKT_KEYS and set(s["slope_bins_pct"]) == BIN_KEYS
        assert set(s["steeper_than_grade_pct"]) == {"10", "15"}
        assert len(s["centroid"]) == 2
        assert sum(s["slope_bins_pct"].values()) == pytest.approx(100.0, abs=0.5)
    assert set(result["kpkt_overall_pct"]) == KPKT_KEYS
    assert all(set(r) == ROUTE_KEYS for r in result["routes"])
    assert all(set(p) == POINT_KEYS for p in result["points"])
    assert all(set(f) == FLAG_KEYS and f["level"] in {"info", "caution", "warning"} for f in result["flags"])
    assert all(set(f) == FOLLOWUP_KEYS for f in result["followups"])
    assert all(isinstance(c, str) and c for c in result["caveats"])
    assert [f["file"] for f in result["figures"]] == FIGURE_FILES
    assert all(set(f) == FIGURE_KEYS and f["title"] and f["caption"] for f in result["figures"])

    meta = result["meta"]
    assert meta["site_label"] == "North block" and meta["stage"] == "exploring" and meta["scheme"] == "lss"
    import hashlib
    assert meta["input_sha256"] == hashlib.sha256((tmp_path / "site.kml").read_bytes()).hexdigest()
    assert result["totals"] == {"polygon_count": 1, "line_count": 1, "point_count": 1,
                                "total_area_ha": result["sites"][0]["area_ha"],
                                "total_line_km": result["routes"][0]["length_km"],
                                "steeper_than_grade_pct": result["sites"][0]["steeper_than_grade_pct"]}
    assert result["location"]["utm_epsg"] == "EPSG:32647"
    assert result["location"]["state"] == "Selangor"
    assert result["dem"]["cells_analysed"] > 0 and result["dem"]["nodata_pct"] == 0.0
    assert result["dem"]["disclaimer"] is None                      # synthetic DEM: no licence notice
    assert result["dem"]["sends_coordinates_to_third_party"] is False
    assert result["location"]["boundary_attribution"] == boundaries.BOUNDARY_ATTRIBUTION
    assert result["contour_interval_m"] >= 5.0

    # flags are sorted most severe first and always include the EIA area items
    order = [{"warning": 0, "caution": 1, "info": 2}[f["level"]] for f in result["flags"]]
    assert order == sorted(order) and "eia_area_items" in codes(result)

    md = (out / "summary.md").read_text(encoding="utf-8")
    assert md == render_summary_md(result)
    for text in ("Lot A", "Cable", "PMU", "Recommended follow-up studies", "1_site_layout.png",
                 result["dem"]["attribution"].split(" ")[0]):
        assert text in md


def test_unknown_meta_values_are_nulled(tmp_path):
    result, _ = screen(tmp_path, point_pm("P", (LON, LAT)), plane_fetcher(2.0),
                       scheme="nuclear", stage="whenever")
    assert result["meta"]["scheme"] is None and result["meta"]["stage"] is None


def test_nodata_becomes_null_and_flagged(tmp_path):
    ring = rect(LON, LAT, 300, 300)
    cut = offset(LON, LAT, 600, 0)[0]

    def terrain(LONS, LATS, X, Y):           # everything east of `cut` is void (sea)
        return np.where(LONS > cut, np.nan, 5.0 + 0.01 * X)

    body = polygon_pm("Coastal", ring) + point_pm("Offshore", offset(LON, LAT, 700, 100))
    result, out = screen(tmp_path, body, function_fetcher(terrain))
    assert result["dem"]["nodata_pct"] > 5.0
    assert "dem_nodata" in codes(result)
    assert result["points"][0]["elev_m"] is None
    _strict_json(out / "result.json")


def test_site_entirely_in_void_has_null_stats(tmp_path):
    land = rect(LON, LAT, 600, 600)
    void = rect(*offset(LON, LAT, 900, 0), 150, 150)
    void_lon = void[0][0] - 0.0005

    def terrain(LONS, LATS, X, Y):
        return np.where(LONS > void_lon, np.nan, 5.0)

    result, out = screen(tmp_path, polygon_pm("Land", land) + polygon_pm("Sea", void),
                         function_fetcher(terrain))
    sea = result["sites"][1]
    assert sea["elev_mean_m"] is None and sea["kpkt_pct"]["I"] is None
    assert result["kpkt_overall_pct"]["I"] == 100.0        # only the measurable site counts
    _strict_json(out / "result.json")


def test_no_dem_coverage(tmp_path):
    fetcher = function_fetcher(lambda LONS, LATS, X, Y: np.full_like(X, np.nan))
    with pytest.raises(ScreeningError) as e:
        screen(tmp_path, polygon_pm("Sea", rect(LON, LAT, 300, 300)), fetcher)
    assert e.value.code == "no_dem_coverage"
    assert not (tmp_path / "out" / "result.json").exists()


def test_dem_unavailable_propagates(tmp_path):
    def down(bbox, settings):
        raise ScreeningError(dem.DEM_UNAVAILABLE_MESSAGE, "dem_unavailable")
    with pytest.raises(ScreeningError) as e:
        screen(tmp_path, polygon_pm("S", rect(LON, LAT, 300, 300)), down)
    assert e.value.code == "dem_unavailable"
    assert "could not be reached" in e.value.message
    assert not (tmp_path / "out" / "result.json").exists()


def test_analysis_bbox_buffer(tmp_path):
    calls: list = []
    ring = rect(LON, LAT, 400, 400)
    screen(tmp_path, polygon_pm("S", ring), function_fetcher(lambda *a: 5.0, calls=calls))
    (bbox,) = calls
    site = validate_upload(tmp_path / "site.kml", make_settings(tmp_path), "site.kml")
    west_buf = GEOD.inv(bbox[0], LAT, site.bbox[0], LAT)[2]
    assert west_buf == pytest.approx(150.0, abs=1.0)   # max(150 m, 10% of 0.4 km)

    big = make_settings(tmp_path)
    site.extent_km = 5.0
    assert GEOD.inv(analysis.analysis_bbox(site)[0], LAT, site.bbox[0], LAT)[2] == pytest.approx(500, abs=2)
    del big


def test_small_site_falls_back_to_sampling(tmp_path):
    body = polygon_pm("Tiny", rect(LON, LAT, 45, 45))
    result, _ = screen(tmp_path, body, plane_fetcher(8.0))
    site = result["sites"][0]
    assert site["cells"] < analysis.SMALL_SITE_MIN_CELLS
    assert site["slope_mean_deg"] == pytest.approx(8.0, abs=0.3)
    assert site["elev_mean_m"] is not None
    assert "small_site" in codes(result)


def test_point_only_input(tmp_path):
    result, out = screen(tmp_path, point_pm("Survey mark", (LON, LAT)), plane_fetcher(4.0))
    assert result["sites"] == [] and result["kpkt_overall_pct"] == {k: None for k in KPKT_KEYS}
    assert result["totals"]["total_area_ha"] == 0.0
    assert all((out / f).exists() for f in FIGURE_FILES)
    assert "eia_area_items" not in codes(result) and "indicative_capacity" not in codes(result)


def test_geometry_repair_caveat(tmp_path):
    ring = [offset(LON, LAT, 0, 0), offset(LON, LAT, 400, 400),
            offset(LON, LAT, 400, 0), offset(LON, LAT, 0, 600)]
    result, _ = screen(tmp_path, polygon_pm("Bowtie", ring), plane_fetcher(2.0))
    assert any("Bowtie" in c and "repaired" in c for c in result["caveats"])


def test_awkward_names_render(tmp_path):
    # '$' would switch matplotlib to mathtext; '|' and '*' are markdown syntax.
    name = "Lot $5 | *A* &amp; &lt;b&gt;"                  # XML-escaped in the KML
    result, out = screen(tmp_path, polygon_pm(name, rect(LON, LAT, 300, 300)), plane_fetcher(3.0))
    assert result["sites"][0]["name"] == "Lot $5 | *A* & <b>"
    md = (out / "summary.md").read_text(encoding="utf-8")
    assert "Lot $5 \\| \\*A\\* & \\<b\\>" in md


# ---------------------------------------------------------------------------
# flags
# ---------------------------------------------------------------------------
def test_kpkt_flag_levels_and_order(tmp_path):
    ring_a = rect(LON, LAT, 300, 300)
    ring_b = rect(*offset(LON, LAT, 700, 0), 300, 300)
    split = offset(LON, LAT, 500, 0)[0]
    t20, t40 = math.tan(math.radians(20)), math.tan(math.radians(40))

    def terrain(LONS, LATS, X, Y):
        return np.where(LONS < split, 10 + t20 * X, 10 + t40 * X)

    result, _ = screen(tmp_path, polygon_pm("A", ring_a) + polygon_pm("B", ring_b), function_fetcher(terrain))
    by_code = {f["code"]: f for f in result["flags"]}
    assert by_code["kpkt_class_ii"]["level"] == "caution"
    assert by_code["kpkt_class_iv"]["level"] == "warning"
    assert "“A”" in by_code["kpkt_class_ii"]["detail"] and "“B”" in by_code["kpkt_class_iv"]["detail"]
    assert codes(result).index("kpkt_class_iv") < codes(result).index("kpkt_class_ii")
    assert "steep_for_ground_pv" in by_code and "high_relief" in by_code
    assert "all_class_i" not in by_code
    titles = [f["title"] for f in result["followups"]]
    assert "Geotechnical investigation and slope stability analysis" in titles
    assert "Geotechnical slope assessment" not in titles


@pytest.fixture
def in_state(monkeypatch):
    """Make the boundary lookup return `state` (DOSM spelling) for every point."""
    def set_state(state, district="Test district"):
        monkeypatch.setattr(boundaries, "lookup", lambda lon, lat: (state, district))
    return set_state


def flag(result, code):
    return next(f for f in result["flags"] if f["code"] == code)


def built(result):
    """Attach flags/follow-ups/caveats to a hand-made result dict, as run_screening does."""
    result["flags"] = flags.build_flags(result)
    result["followups"] = flags.build_followups(result)
    result["caveats"] = flags.build_caveats(result)
    return result


def bins(**kw):
    """Slope bins from keyword shares (b0_2=..., b5_10=..., b25_35=..., gt35=...); rest in 0-2."""
    names = {"b0_2": "0-2", "b2_5": "2-5", "b5_10": "5-10", "b10_15": "10-15",
             "b15_25": "15-25", "b25_35": "25-35", "gt35": ">35"}
    out = {v: 0.0 for v in names.values()}
    for k, v in kw.items():
        out[names[k]] = float(v)
    out["0-2"] = 100.0 - sum(v for k, v in out.items() if k != "0-2")
    return out


# --- hill and highland guideline: slope classes --------------------------------
@pytest.mark.parametrize("slope_deg, code, level, constraint", [
    (20.0, "kpkt_class_ii", "caution", "moderate"),
    (30.0, "kpkt_class_iii", "warning", "high"),
    (40.0, "kpkt_class_iv", "warning", "extreme"),
])
def test_kpkt_class_flags_are_slope_based(tmp_path, slope_deg, code, level, constraint):
    result, _ = screen(tmp_path, polygon_pm("P", rect(LON, LAT, 300, 300)), plane_fetcher(slope_deg))
    f = flag(result, code)
    assert f["level"] == level and "slope-based" in f["title"]
    assert "slope-based indication" in f["detail"] and "geotechnical condition" in f["detail"]
    assert f"{constraint} geotechnical constraint" in f["detail"]
    assert "solar farm is not among the uses" in f["detail"] or code == "kpkt_class_iv"
    assert f["source"] == flags.SRC_GPP_CLASSES and "Jadual 1" in f["source"]
    assert "all_class_i" not in codes(result)
    if code == "kpkt_class_iv":
        assert "exemption" in f["detail"] and "(10% or more)" in f["detail"]
        assert "national importance" in f["detail"] and "does not say whether a solar farm" in f["detail"]


def test_kpkt_class_iv_small_share_points_to_exemption_route():
    f = next(f for f in flags.build_flags(result_with([site_result(bins=bins(b15_25=20, gt35=4))]))
             if f["code"] == "kpkt_class_iv")
    assert "4.0% of its area (under 10%)" in f["detail"] and "less than 10%" in f["detail"]


def test_kpkt_threshold_is_more_than_half_a_percent():
    at = flags.build_flags(result_with([site_result(bins=bins(b15_25=0.5))]))
    above = flags.build_flags(result_with([site_result(bins=bins(b15_25=0.6))]))
    assert "kpkt_class_ii" not in [f["code"] for f in at] and "all_class_i" in [f["code"] for f in at]
    assert "kpkt_class_ii" in [f["code"] for f in above] and "all_class_i" not in [f["code"] for f in above]


def test_all_class_i_wording_and_schemes():
    flat = [site_result()]
    f = next(f for f in flags.build_flags(result_with(flat)) if f["code"] == "all_class_i")
    assert f["level"] == "info" and "slope-based indication" in f["detail"]
    assert "ex-mining" in f["detail"] and "flood threat" in f["detail"]
    assert "all_class_i" not in [f["code"] for f in flags.build_flags(result_with(flat, scheme="fpv"))]
    assert "all_class_i" in [f["code"] for f in flags.build_flags(result_with(flat, scheme="rooftop"))]


def test_guideline_reports_trigger_and_wording():
    lowland = flags.build_flags(result_with([site_result()]))
    assert "guideline_reports" not in [f["code"] for f in lowland]
    sloped = next(f for f in flags.build_flags(result_with([site_result(bins=bins(b15_25=3))]))
                  if f["code"] == "guideline_reports")
    assert sloped["level"] == "info" and "15° or steeper" in sloped["detail"]
    for words in ("geotechnical investigation and slope stability analysis",
                  "geological and geomorphological mapping", "Board of Geologists",
                  "drainage report under MSMA", "registered with JPS", "DOE-registered EIA consultant",
                  "50 hectares", "detailed EIA", "earthworks plan", "registered with BEM"):
        assert words in sloped["detail"], words
    high = next(f for f in flags.build_flags(result_with([site_result(elev_min=150, elev_max=160)]))
                if f["code"] == "guideline_reports")
    assert "150 m or more" in high["detail"] and "15° or steeper" not in high["detail"]
    sabah = next(f for f in flags.build_flags(result_with([site_result(bins=bins(b15_25=3))], state="Sabah"))
                 if f["code"] == "guideline_reports")
    assert "JPBD Semenanjung Malaysia" in sabah["detail"] and "in Sabah" in sabah["detail"]


# --- elevation bands -------------------------------------------------------------
@pytest.mark.parametrize("base, code, level", [
    (140.0, None, None),
    (200.0, "hill_land_band", "caution"),
    (450.0, "highland_band", "warning"),
    (1200.0, "mountain_band", "warning"),
])
def test_elevation_bands(tmp_path, base, code, level):
    result, _ = screen(tmp_path, polygon_pm("Lot", rect(LON, LAT, 300, 300)), plane_fetcher(0.0, base=base))
    bands = [c for c in codes(result) if c.endswith("_band")]
    assert bands == ([code] if code else [])
    if not code:
        return
    f = flag(result, code)
    assert f["level"] == level and f"up to {base:,.0f} m" in f["detail"]
    assert "guideline_reports" in codes(result)
    if code == "hill_land_band":
        assert "Tanah Bukit" in f["detail"] and "KSAS Level 3" in f["detail"]
        assert "controlled development" in f["detail"]
    else:
        assert "Special Management Areas" in f["detail"] and "Bukit Fraser" in f["detail"]
        assert "First Schedule item 5(a)" in f["detail"] and "P.U. (A) 195/2015" in f["source"]
    if code == "highland_band":
        assert "Tanah Tinggi" in f["detail"] and "eco-tourism" in f["detail"]
        assert "a solar farm is not a listed use" in f["detail"]
    if code == "mountain_band":
        assert "Gunung" in f["detail"] and "national importance" in f["detail"]
    titles = [x["title"] for x in result["followups"]]
    assert "Confirm EIA applicability with a DOE-registered EIA consultant" in titles


def test_band_uses_each_sites_highest_point():
    sites = [site_result("Low", elev_min=100, elev_max=180), site_result("High", elev_min=250, elev_max=320)]
    out = {f["code"]: f for f in flags.build_flags(result_with(sites))}
    assert "“Low”: up to 180 m (lowest 100 m)" in out["hill_land_band"]["detail"]
    assert "“High”" not in out["hill_land_band"]["detail"]
    assert "“High”: up to 320 m" in out["highland_band"]["detail"]


# --- EIA Order 2015 ---------------------------------------------------------------
def test_eia_slope_item13_schedules(tmp_path):
    result, _ = screen(tmp_path, polygon_pm("Steep", rect(LON, LAT, 300, 300)), plane_fetcher(30.0))
    f = flag(result, "eia_slope_item13")
    assert f["level"] == "warning" and "100.0% of its area" in f["detail"]
    assert "which points to Second Schedule item 13(a)" in f["detail"]
    assert "public display and public comment" in f["detail"] and "understates" in f["detail"]
    assert "P.U. (A) 195/2015" in f["source"]
    part = next(f for f in flags.build_flags(result_with([site_result(bins=bins(b25_35=12))]))
                if f["code"] == "eia_slope_item13")
    assert "12.0% of its area (under 50%, which points to First Schedule item 13)" in part["detail"]
    none = flags.build_flags(result_with([site_result(bins=bins(b25_35=0.5, gt35=5))]))
    assert "eia_slope_item13" not in [f["code"] for f in none]


def test_eia_route_35(tmp_path):
    west, east = (LON, LAT), offset(LON, LAT, 600, 0)
    steep, _ = screen(tmp_path / "a", line_pm("Haul road", [west, east]), plane_fetcher(36.0),
                      settings=make_settings(tmp_path))
    f = flag(steep, "eia_route_35")
    assert f["level"] == "warning" and "Second Schedule (item 13(b))" in f["detail"]
    assert "If an access road is built along this route" in f["detail"]
    assert f["source"] == flags.SRC_EIA_ROUTE
    gentler, _ = screen(tmp_path / "b", line_pm("Haul road", [west, east]), plane_fetcher(34.0),
                        settings=make_settings(tmp_path))
    assert "eia_route_35" not in codes(gentler)
    assert flags.EIA_ROUTE_GRADE_PCT == pytest.approx(70.02, abs=0.01)


def test_eia_area_items_replace_eia_check():
    f = next(f for f in flags.build_flags(result_with([site_result(area_ha=61.86)]))
             if f["code"] == "eia_area_items")
    assert "eia_check" not in [x["code"] for x in flags.build_flags(result_with([site_result()]))]
    assert f["level"] == "info" and "not listed among the power-generation items" in f["detail"]
    for item in ("First Schedule 5(a)", "Second Schedule 5(a)", "First Schedule 5(d)",
                 "Second Schedule 5(f)", "Second Schedule 3(b)", "First Schedule 17",
                 "not settled", "61.86 ha", "DOE-registered EIA consultant"):
        assert item in f["detail"], item
    unknown = next(f for f in flags.build_flags(result_with([site_result()], state=None))
                   if f["code"] == "eia_area_items")
    assert "could not be identified" in unknown["detail"]


def test_sabah_and_sarawak_use_the_limited_scope_branch(tmp_path, in_state):
    in_state("Sabah", "Ranau")
    body = (polygon_pm("Hill", rect(LON, LAT, 300, 300))
            + line_pm("Road", [offset(LON, LAT, -100, 150), offset(LON, LAT, 400, 150)]))
    result, _ = screen(tmp_path, body, plane_fetcher(36.0, base=400.0))
    c = codes(result)
    assert result["location"]["state"] == "Sabah"
    assert "eia_slope_item13" not in c and "eia_route_35" not in c
    regime = flag(result, "eia_slope_state_regime")
    assert regime["level"] == "info" and "do not apply in Sabah" in regime["title"]
    assert "“Road”" in regime["detail"] and "state authority" in regime["detail"]
    area = flag(result, "eia_area_items")
    assert "limited scope in Sabah" in area["title"] and "First Schedule 5(a)" not in area["detail"]
    assert "forest-conversion items (5)" in area["detail"] and area["source"] == flags.SRC_EIA_SCOPE
    high = flag(result, "highland_band")
    assert "5(a)" not in high["detail"] and "Special Management Areas" not in high["detail"]
    sarawak = flags.build_flags(result_with([site_result(bins=bins(b25_35=5))], state="Sarawak"))
    assert "eia_slope_state_regime" in [f["code"] for f in sarawak]
    assert "eia_slope_item13" not in [f["code"] for f in sarawak]


# --- Act 133 and state rules ----------------------------------------------------------
def test_sdba_geotech_needs_steep_share_and_relief():
    def run(**kw):
        return {f["code"]: f for f in flags.build_flags(result_with([site_result(**kw)]))}
    hit = run(bins=bins(b25_35=1.0), relief=12.0)["sdba_geotech"]
    assert hit["level"] == "caution" and "Accredited Checker" in hit["detail"]
    assert "twenty-five degrees" in hit["detail"] and hit["source"] == flags.SRC_SDBA
    assert "sdba_geotech" not in run(bins=bins(b25_35=1.0), relief=9.0)
    assert "sdba_geotech" not in run(bins=bins(b25_35=0.4), relief=50.0)
    assert "sdba_geotech" in run(bins=bins(gt35=2.0), relief=40.0)          # > 25° includes Class IV


def test_penang_hill_rule(tmp_path, in_state):
    in_state("Pulau Pinang", "Timur Laut")
    high, _ = screen(tmp_path / "a", polygon_pm("Bukit", rect(LON, LAT, 300, 300)),
                     plane_fetcher(0.0, base=100.0), settings=make_settings(tmp_path))
    f = flag(high, "penang_hill")
    assert f["level"] == "warning" and "up to 100 m" in f["detail"]
    for words in ("76 m (250 ft)", "steeper than 25°", "RSNPP 2030", "24 Oct 2019", "RSNPP 2040",
                  "9 Sep 2026", "as reported", "PLANMalaysia@Pulau Pinang", "MBPP/MBSP"):
        assert words in f["detail"], words
    assert "News reports" in f["source"]
    low, _ = screen(tmp_path / "b", polygon_pm("Flat", rect(LON, LAT, 300, 300)),
                    plane_fetcher(0.0, base=50.0), settings=make_settings(tmp_path))
    assert "penang_hill" not in codes(low)
    steep = flags.build_flags(result_with([site_result(elev_max=60, bins=bins(b25_35=2))],
                                          state="Pulau Pinang"))
    assert "2.0% of its area steeper than 25°" in next(f for f in steep if f["code"] == "penang_hill")["detail"]
    elsewhere = flags.build_flags(result_with([site_result(elev_max=120)], state="Kedah"))
    assert "penang_hill" not in [f["code"] for f in elsewhere]


def test_pahang_solar_rule(tmp_path, in_state):
    in_state("Pahang", "Bentong")
    rolling, _ = screen(tmp_path / "a", polygon_pm("Rolling", rect(LON, LAT, 300, 300)),
                        plane_fetcher(12.0), settings=make_settings(tmp_path))
    f = flag(rolling, "pahang_solar_10deg")
    assert f["level"] == "warning" and "100.0%" in f["detail"]
    assert "melebihi 10 darjah adalah tidak sesuai" in f["detail"] and "GPP PHG 03" in f["source"]
    assert "JTKSAS" not in f["detail"]
    assert "industrial activity" in flag(rolling, "eia_area_items")["detail"]
    steep, _ = screen(tmp_path / "b", polygon_pm("Steep", rect(LON, LAT, 300, 300)),
                      plane_fetcher(30.0), settings=make_settings(tmp_path))
    g = flag(steep, "pahang_solar_10deg")
    assert "JTKSAS" in g["detail"] and "25° or steeper" in g["detail"] and "(Pahang) 2019" in g["source"]
    high = next(f for f in flags.build_flags(result_with(
        [site_result(elev_min=280, elev_max=320, bins=bins(b10_15=20))], state="Pahang"))
        if f["code"] == "pahang_solar_10deg")
    assert "reaches 300 m or more" in high["detail"] and "JTKSAS" in high["detail"]
    gentle, _ = screen(tmp_path / "c", polygon_pm("Gentle", rect(LON, LAT, 300, 300)),
                       plane_fetcher(5.0), settings=make_settings(tmp_path))
    assert "pahang_solar_10deg" not in codes(gentle)


# --- ground-mounted PV slope context and capacity ------------------------------------------
@pytest.mark.parametrize("slope_deg, level", [(12.0, "caution"), (7.0, "info"), (4.0, None)])
def test_steep_for_ground_pv_levels(tmp_path, slope_deg, level):
    result, _ = screen(tmp_path, polygon_pm("Lot", rect(LON, LAT, 300, 300)), plane_fetcher(slope_deg))
    site = result["sites"][0]
    expect_15 = 100.0 if slope_deg > flags.PV_SLOPE_TRACKER_DEG else 0.0
    expect_10 = 100.0 if slope_deg > flags.PV_SLOPE_FIXED_DEG else 0.0
    assert site["steeper_than_grade_pct"] == {"10": expect_10, "15": expect_15}
    if level is None:
        assert "steep_for_ground_pv" not in codes(result)
        return
    f = flag(result, "steep_for_ground_pv")
    assert f["level"] == level
    assert f"“Lot”: {expect_15:.0f}% and {expect_10:.0f}%" in f["detail"]
    assert "estimated from the slope bands" not in f["detail"]              # exact shares used
    for words in ("IFC", "no numeric limit", "DuraTrack HZ v3", "Vanguard 1P", "FixOrigin",
                  "NREL", "do not show whether any product suits this site"):
        assert words in f["detail"], words
    assert "s.6.3.4" in f["source"]


def test_steep_for_ground_pv_skipped_for_fpv_and_rooftop():
    sites = [site_result(bins=bins(b10_15=50))]
    for scheme in ("fpv", "rooftop"):
        assert "steep_for_ground_pv" not in [f["code"] for f in flags.build_flags(result_with(sites, scheme=scheme))]
    assert "steep_for_ground_pv" in [f["code"] for f in flags.build_flags(result_with(sites, scheme=None))]


def test_share_steeper_interpolates_within_a_bin():
    site = site_result(bins=bins(b5_10=50))
    assert flags.share_steeper(site, 10.0) == pytest.approx(0.0)
    assert flags.share_steeper(site, 5.0) == pytest.approx(50.0)
    assert flags.share_steeper(site, 8.5) == pytest.approx(50.0 * 1.5 / 5.0)
    assert flags.grade_share(site, 15) == (pytest.approx(50.0 * (10 - flags.PV_SLOPE_TRACKER_DEG) / 5), False)
    site["steeper_than_grade_pct"] = {"10": 40.0, "15": 12.0}
    assert flags.grade_share(site, 15) == (12.0, True)
    assert flags.share_steeper({"slope_bins_pct": {}}, 8.5) is None


def test_indicative_capacity_math():
    def cap(sites, **kw):
        return next((f for f in flags.build_flags(result_with(sites, **kw)) if f["code"] == "indicative_capacity"), None)
    f = cap([site_result(area_ha=12.0, grades={"10": 40.0, "15": 25.0})])
    # 12 ha / 1.2..0.8 ha per MWp = 10..15 MWp; flatter than 8.5°: 9 ha -> 7.5..11.2 MWp
    assert "12.00 ha gives about 10–15 MWp" in f["detail"]
    assert "the 9.0 ha flatter than about 8.5°" in f["detail"] and "7.5–11.2 MWp" in f["detail"]
    for words in ("gross", "setbacks", "access roads", "drainage reserves", "shading", "grid limits",
                  "Thailand and Indonesia", "pitch"):
        assert words in f["detail"], words
    assert f["level"] == "info" and "Table 7" in f["source"]
    # Two sites, one estimated from the bins (5-10° band split linearly).
    two = cap([site_result("A", area_ha=40.0, grades={"10": 0.0, "15": 0.0}),
               site_result("B", area_ha=20.0, bins=bins(b5_10=50))])
    flat_b = 20.0 * (1 - 0.5 * (10 - flags.PV_SLOPE_TRACKER_DEG) / 5)
    assert f"the {40 + flat_b:,.1f} ha flatter" in two["detail"] and "estimated from the slope bands" in two["detail"]
    assert "50–75 MWp" in two["detail"]
    flat = cap([site_result(area_ha=42.16, grades={"10": 0.0, "15": 0.0})])
    assert "35–53 MWp; on the DEM all of it is flatter than about 8.5°" in flat["detail"]
    assert cap([site_result(area_ha=0.9)]) is None
    assert cap([site_result()], scheme="fpv") is None and cap([site_result()], scheme="rooftop") is None
    assert cap([site_result()], scheme=None) is not None and cap([site_result()], scheme="cress") is not None


def test_capacity_without_enough_gentle_ground_gives_no_figure():
    """H1: a site with almost no ground flatter than 8.5° got "0.0–0.0 MWp" / "0.1–0.1 MWp"."""
    def cap(**kw):
        return next(f for f in flags.build_flags(result_with([site_result(**kw)]))
                    if f["code"] == "indicative_capacity")["detail"]
    steep = cap(area_ha=14.6, grades={"10": 100.0, "15": 100.0})
    assert "0.0–0.0" not in steep and "only 0.0 ha is flatter than about 8.5°" in steep
    assert "too little for an indicative figure" in steep
    sliver = cap(area_ha=36.77, grades={"10": 99.9, "15": 99.7})
    assert "0.1–0.1" not in sliver and "only 0.1 ha is flatter" in sliver
    assert flags._mwp_range(0.05) == "under 0.1" and flags._mwp_range(0.5) == "0.42–0.62"
    assert flags._mwp_range(1.0) == "0.8–1.2" and flags._mwp_range(12.0) == "10–15"


def test_capacity_uses_the_overall_share_when_present():
    """GEO-2: with the union-based share in totals, the flatter area is not summed per site."""
    lot = site_result("Lot", area_ha=100.0, grades={"10": 50.0, "15": 50.0})
    block = site_result("Block", area_ha=28.0, grades={"10": 0.0, "15": 0.0})
    r = result_with([lot, block])
    r["totals"] = {"total_area_ha": 100.0, "steeper_than_grade_pct": {"10": 50.0, "15": 50.0}}
    f = next(f for f in flags.build_flags(r) if f["code"] == "indicative_capacity")
    assert "100.00 ha gives about 83–125 MWp" in f["detail"]
    assert "the 50.0 ha flatter than about 8.5°" in f["detail"] and "42–62 MWp" in f["detail"]


def test_all_class_i_uses_the_combined_share_at_15_degrees_or_more():
    """GEO-3: 0.5% + 0.5% + 0.4% at 15° or more is 1.4%: not "no more than 0.5%"."""
    site = site_result(bins=bins(b15_25=0.5, b25_35=0.5, gt35=0.4))
    out = [f["code"] for f in flags.build_flags(result_with([site]))]
    assert "all_class_i" not in out and "guideline_reports" in out
    titles = [f["title"] for f in flags.build_followups(built(result_with([site])))]
    assert "Geotechnical investigation and slope stability analysis" in titles


def test_coarse_grid_is_flagged_and_suppresses_all_class_i():
    """GEO-4: OpenTopoData's <= 1,000-point grid over a large site (~200 m) understates steep
    ground several-fold; say so and give no "all Class I" reading."""
    r = result_with([site_result()], provider="opentopodata")
    r["dem"] = {**r["dem"], "grid_spacing_m": 196.8, "nominal_resolution_m": 30}
    out = {f["code"]: f for f in flags.build_flags(r)}
    assert "coarse_grid" in out and "all_class_i" not in out
    assert out["coarse_grid"]["level"] == "caution" and "197 m" in out["coarse_grid"]["detail"]
    fine = {f["code"] for f in flags.build_flags(result_with([site_result()]))}
    assert "coarse_grid" not in fine and "all_class_i" in fine
    # A 1 m local DTM averaged to ~30 m for a large site is the normal case, not "coarse".
    lidar = result_with([site_result()], provider="geotiff")
    lidar["dem"] = {**lidar["dem"], "grid_spacing_m": 31.0, "nominal_resolution_m": 1}
    assert "coarse_grid" not in {f["code"] for f in flags.build_flags(lidar)}


def test_peninsular_instruments_are_not_applied_as_rules_in_sabah_and_sarawak():
    """H2: the 2009 guideline is a JPBD Semenanjung document and Act 133 applies only to West
    Malaysia; in Sabah and Sarawak the report says so and raises no Act 133 flag."""
    hill = [site_result("Kundasang", elev_min=1100, elev_max=1400, relief=300,
                        bins=bins(b15_25=20, b25_35=20, gt35=20))]
    for state in ("Sabah", "Sarawak"):
        out = {f["code"]: f for f in flags.build_flags(result_with(hill, state=state))}
        assert "sdba_geotech" not in out
        for code in ("kpkt_class_ii", "kpkt_class_iii", "kpkt_class_iv", "mountain_band"):
            assert f"issued for Peninsular Malaysia; in {state} it is a reference only" in out[code]["detail"], code
        geotech = {f["title"]: f["detail"] for f in flags.build_followups(built(result_with(hill, state=state)))}
        assert "Accredited Checker" not in geotech["Geotechnical investigation and slope stability analysis"]
    flat = flags.all_class_i_flag([site_result()], "Sabah")
    assert "reference only" in flat["detail"]
    band = flags.hill_land_band_flag([site_result(elev_min=160, elev_max=200)], result_with([])["dem"], "Sarawak")
    assert "reference only" in band["detail"]
    selangor = {f["code"]: f for f in flags.build_flags(result_with(hill, state="Selangor"))}
    assert "sdba_geotech" in selangor and "reference only" not in selangor["kpkt_class_iv"]["detail"]
    labuan = {f["code"] for f in flags.build_flags(result_with(hill, state="W.P. Labuan"))}
    assert "sdba_geotech" in labuan                         # Act 133 extends to Labuan


def test_route_ground_slope_flag_rules():
    """H3: item 13(b) is about the ground the route traverses; a route counts once at least
    30 m of it lies on ground of 35° or more."""
    def route(**kw):
        return {**route_result(max_grade_pct=3.0), **kw}
    hit = flags.build_flags(result_with([], routes=[route(max_slope_deg=41.2, length_on_35deg_m=850.0)]))
    f = next(f for f in hit if f["code"] == "eia_route_35")
    assert "about 850 m of the route on ground of 35° or steeper, up to 41°" in f["detail"]
    assert "not the route's own gradient" in f["detail"]
    short = flags.build_flags(result_with([], routes=[route(max_slope_deg=36.0, length_on_35deg_m=0.0)]))
    assert "eia_route_35" not in [x["code"] for x in short]
    old_format = flags.build_flags(result_with([], routes=[route_result(max_grade_pct=80)]))
    assert "eia_route_35" in [x["code"] for x in old_format]
    regime = next(x for x in flags.build_flags(result_with(
        [], state="Sabah", routes=[route(max_slope_deg=41.2, length_on_35deg_m=850.0)]))
        if x["code"] == "eia_slope_state_regime")
    assert "about 850 m of the route on ground of 35° or steeper" in regime["detail"]
    assert analysis.ROUTE_STEEP_DEG == flags.EIA_ROUTE_SLOPE_DEG


def test_road_along_a_contour_on_steep_ground_raises_eia_13b(tmp_path):
    """H3: a nearly level road cut along a 40° hillside traverses ground of 35° or more."""
    start = (LON, LAT)
    road = line_pm("Access road (along contour)", [start, offset(LON, LAT, 0, 1500)])
    result, _ = screen(tmp_path, road, plane_fetcher(40.0, direction="east"))
    r = result["routes"][0]
    assert r["max_grade_pct"] < 1.0
    assert r["max_slope_deg"] == pytest.approx(40.0, abs=0.5)
    assert r["length_on_35deg_m"] == pytest.approx(1500.0, rel=0.05)
    assert "eia_route_35" in codes(result)
    gentle, _ = screen(tmp_path / "gentle", road, plane_fetcher(20.0, direction="east"),
                       settings=make_settings(tmp_path))
    assert "eia_route_35" not in codes(gentle) and gentle["routes"][0]["length_on_35deg_m"] == 0.0


def test_route_sampling_is_capped_for_very_long_lines(monkeypatch, settings):
    """appsec-3: samples along a route are capped (vertices kept), whatever its length."""
    monkeypatch.setattr(analysis, "MAX_ROUTE_SAMPLES", 200)
    a, b = (101.40, 3.40), (101.53, 3.41)
    feat = analysis.Feature(name="Zig", kind="line", coords=[a if i % 2 == 0 else b for i in range(12)])
    grid = plane_fetcher(0.0)((101.39, 3.39, 101.54, 3.42), settings)
    slope = np.zeros_like(grid.z)
    r = analysis._route_stats(feat, grid, 30.0, slope)
    assert r.lons.size <= 200 + len(feat.coords)
    assert r.length_m == pytest.approx(11 * 14_480, rel=0.02)
    lons, lats = analysis._sample_line([a, b], 1000.0)          # vectorised sampler keeps both ends
    assert lons[0] == a[0] and lons[-1] == b[0] and lats[-1] == b[1] and lons.size == 16


# --- FPV ---------------------------------------------------------------------------------
def test_fpv_flags(tmp_path):
    flat, _ = screen(tmp_path / "flat", polygon_pm("Pond", rect(LON, LAT, 400, 400)),
                     plane_fetcher(0.0, base=31.0), settings=make_settings(tmp_path), scheme="fpv")
    assert "fpv_dem_epoch" in codes(flat) and "fpv_land_inside" not in codes(flat)
    assert "all_class_i" not in codes(flat) and "steep_for_ground_pv" not in codes(flat)
    assert "indicative_capacity" not in codes(flat)
    titles = [f["title"] for f in flat["followups"]]
    fpv_only = {"Bathymetric survey", "Seasonal water-level records", "Bund geotechnical assessment"}
    assert fpv_only <= set(titles)
    assert "flattened" not in flag(flat, "fpv_dem_epoch")["detail"]       # synthetic DEM, not Copernicus

    hilly, _ = screen(tmp_path / "hilly", polygon_pm("Pond", rect(LON, LAT, 400, 400)),
                      plane_fetcher(8.0), settings=make_settings(tmp_path), scheme="fpv")
    land = next(f for f in hilly["flags"] if f["code"] == "fpv_land_inside")
    assert land["level"] == "caution" and "post-dates" in land["detail"]

    lss, _ = screen(tmp_path / "lss", polygon_pm("Pond", rect(LON, LAT, 400, 400)),
                    plane_fetcher(0.0), settings=make_settings(tmp_path), scheme="lss")
    assert not [c for c in codes(lss) if c.startswith("fpv")]
    assert "Bathymetric survey" not in [f["title"] for f in lss["followups"]]

    cop = next(f for f in flags.build_flags(result_with([site_result()], scheme="fpv"))
               if f["code"] == "fpv_dem_epoch")
    assert "flattened during editing" in cop["detail"] and "says nothing about depth" in cop["detail"]


# --- builders ----------------------------------------------------------------------------
def test_flag_thresholds_from_numbers_only():
    """Rules read numbers, never names: identical numbers, different names -> same codes."""
    base = result_with([])
    site = site_result(elev_max=20.0, relief=3.0, area_ha=10.0)
    a = flags.build_flags({**base, "totals": {"total_area_ha": 10.0},
                           "sites": [{**site, "name": "pond FPV steep Class IV hill Penang"}]})
    b = flags.build_flags({**base, "totals": {"total_area_ha": 10.0}, "sites": [{**site, "name": "Lot 7"}]})
    assert [f["code"] for f in a] == [f["code"] for f in b] == [
        "all_class_i", "indicative_capacity", "eia_area_items"]


def test_every_flag_cites_an_instrument_where_it_states_a_rule():
    sites = [site_result("Hill", elev_min=200, elev_max=1100, bins=bins(b10_15=20, b15_25=20, b25_35=20, gt35=5))]
    for state in ("Selangor", "Pulau Pinang", "Pahang", "Sabah"):
        out = flags.build_flags(result_with(sites, state=state, routes=[route_result(max_grade_pct=80)]))
        for f in out:
            if f["code"] not in {"route_grade", "small_site", "dem_nodata", "fpv_land_inside", "fpv_dem_epoch"}:
                assert f["source"], f["code"]
            assert "'" not in f["title"] and '"' not in f["title"] and "&" not in f["title"]


def test_followups_align_with_flags():
    plain = {f["title"] for f in flags.build_followups(built(result_with([site_result()])))}
    assert {"Licensed topographic survey", "Geological map review (JMG)",
            "Rainfall and climate data (MET Malaysia)", "Surrounding land-use scan (1 / 5 / 10 km)",
            "Land title, zoning and local authority requirements",
            "Confirm EIA applicability with a DOE-registered EIA consultant"} <= plain
    assert "Geotechnical investigation and slope stability analysis" not in plain
    steep = built(result_with([site_result(bins=bins(b15_25=20, b25_35=10), relief=40)]))
    fu = {f["title"]: f["detail"] for f in steep["followups"]}
    for title in ("Geotechnical investigation and slope stability analysis",
                  "Geological and geomorphological mapping", "Drainage report to MSMA", "Earthworks plan"):
        assert title in fu, title
    assert "Accredited Checker" in fu["Geotechnical investigation and slope stability analysis"]
    assert "Board of Geologists" in fu["Geological and geomorphological mapping"]
    assert "Act 458" in fu["Licensed topographic survey"]
    no_eia = built(result_with([]))
    assert "Confirm EIA applicability with a DOE-registered EIA consultant" not in {
        f["title"] for f in no_eia["followups"]}


def test_caveats_by_provider():
    cop = flags.build_caveats(result_with([site_result()]))
    text = " ".join(cop)
    for words in ("Act 458", "not for planning applications", "vegetation and buildings were not removed",
                  "Water bodies were flattened", "better than 4 m", "better than 2 m on slopes up to 20%",
                  "26.55 m", "+12.09 m", "Hawker et al. 2022", "Environ. Res. Lett. 17 024016",
                  "38 GNSS benchmarks", "2.45 m", "ASPRS", "twice the 90% vertical error",
                  "against true ground", "absolute LE90 of under 4 m", "about 8 m",
                  "not to a mapping standard", "understated", "1–7°N", "s.6.3.4", "DOSM",
                  "not legal advice"):
        assert words in text, words
    # The contour basis is the ABSOLUTE LE90 (ASPRS/NMAS test against true elevations), and the
    # caveat makes no claim about a floor that a configured CONTOUR_MIN_INTERVAL_M can undercut.
    assert "relative LE90" not in text and "finest honest" not in text and "never draws" not in text
    fine = result_with([site_result()])
    fine["contour_interval_m"] = 2.0
    fine_text = " ".join(flags.build_caveats(fine))
    assert "Contours are drawn every 2 m." in fine_text and "finer than 5 m" not in fine_text
    assert "OpenTopoData" not in text
    otd = " ".join(flags.build_caveats(result_with([site_result()], provider="opentopodata")))
    assert "Hawker" not in otd and "Farr et al. 2007" in otd and "OpenTopoData public API" in otd
    tif = {**result_with([site_result()], provider="geotiff")}
    tif["dem"] = {**tif["dem"], "model_type": "DTM (bare earth)"}
    tif_text = " ".join(flags.build_caveats(tif))
    assert "Elevation model type: DTM (bare earth)" in tif_text and "ASPRS" not in tif_text


def test_figure_stamp():
    stamp = flags.figure_stamp({"provider": "copernicus", "name": "Copernicus DEM GLO-30",
                                "epoch": dem.COPERNICUS_EPOCH})
    assert stamp == ("Desktop screening — not a survey · DEM: Copernicus DEM GLO-30 "
                     "(December 2010 – January 2015, TanDEM-X acquisitions) · EcoEnergy Consultancy\n"
                     "Copernicus WorldDEM-30 © DLR/Airbus, provided under COPERNICUS by EU & ESA")
    srtm = flags.figure_stamp({"provider": "opentopodata", "name": dem.SRTM_NAME, "epoch": dem.SRTM_EPOCH})
    assert "\n" not in srtm and "11–22 February 2000" in srtm


def test_figure_footer_fits_on_the_narrowest_figure():
    """Both stamp lines fit inside a 7.5 in wide figure at the footer font size."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from app.terrain import figures

    stamp = flags.figure_stamp({"provider": "copernicus", "name": dem.COPERNICUS_NAME,
                                "epoch": dem.COPERNICUS_EPOCH})
    fig = Figure(figsize=(7.5, 5.9), dpi=figures.DPI)
    canvas = FigureCanvasAgg(fig)
    for line in stamp.split("\n"):
        t = fig.text(0.01, 0.0, line, fontsize=figures.FOOTER_FONT_PT)
        assert t.get_window_extent(canvas.get_renderer()).x1 < fig.bbox.width


def test_summary_md_prints_dem_disclaimer(tmp_path):
    result, out = screen(tmp_path, polygon_pm("Lot", rect(LON, LAT, 300, 300)), plane_fetcher(2.0))
    assert dem.COPERNICUS_DISCLAIMER not in (out / "summary.md").read_text(encoding="utf-8")
    result["dem"]["disclaimer"] = dem.COPERNICUS_DISCLAIMER
    md = render_summary_md(result)
    assert "The organisations in charge of the Copernicus programme" in md
    assert "Department of Statistics Malaysia" in md


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("x, nice", [(0.7, 0.5), (1.2, 1.0), (2.6, 2.0), (4.0, 5.0), (8.0, 10.0),
                                     (23, 20), (60, 50)])
def test_nice_interval(x, nice):
    assert analysis.nice_interval(x) == nice


def test_contour_interval_respects_minimum(settings):
    assert analysis.contour_interval(4.0, settings) == 5.0
    assert analysis.contour_interval(180.0, settings) == 20.0
    assert analysis.contour_interval(0.0, settings) == 5.0


@pytest.mark.parametrize("lon, lat, epsg", [(100.37, 6.05, "EPSG:32647"), (103.5, 3.0, "EPSG:32648"),
                                            (110.3, 1.5, "EPSG:32649"), (116.1, 6.0, "EPSG:32650")])
def test_utm_epsg(lon, lat, epsg):
    assert analysis.utm_epsg(lon, lat) == epsg


@pytest.mark.parametrize("lon, lat, state, district", [
    (100.3555, 6.0423, "Kedah", "Kota Setar"),            # Kedah fixture (Lot A paddy)
    (100.37, 6.05, "Kedah", "Kota Setar"),
    (101.9037, 3.5071, "Pahang", "Bentong"),              # Pahang fixture
    (101.0577, 4.5477, "Perak", "Kinta"),                 # Perak FPV fixture
    (101.6869, 2.9358, "W.P. Putrajaya", "W.P. Putrajaya"),
    (110.35, 1.55, "Sarawak", "Kuching"),
    (116.07, 5.98, "Sabah", "Kota Kinabalu"),
    (100.33, 5.41, "Pulau Pinang", "Timur Laut"),
    (102.25, 2.20, "Melaka", "Melaka Tengah"),
    (101.69, 3.14, "W.P. Kuala Lumpur", "W.P. Kuala Lumpur"),
])
def test_boundary_lookup(lon, lat, state, district):
    assert boundaries.lookup(lon, lat) == (state, district)


def test_boundary_lookup_offshore():
    assert boundaries.lookup(104.5, 2.0) == (None, None)          # South China Sea
    # About 2.3 km off the Kedah coast: no polygon contains it, the nearest is within 5 km.
    pt = boundaries.Point(100.30, 6.05)
    assert not len(boundaries._load().tree.query(pt, predicate="intersects"))
    assert boundaries.lookup(100.30, 6.05) == ("Kedah", "Kota Setar")
    assert boundaries.lookup(100.26, 6.05) == (None, None)        # about 5.7 km offshore


def test_boundary_data_is_dosm_and_repaired():
    layer = boundaries._load()
    assert len(layer.geoms) == 160
    assert all(g.is_valid and g.geom_type in ("Polygon", "MultiPolygon") for g in layer.geoms)
    states = {s for s, _ in layer.names}
    assert len(states) == 16 and {"Pulau Pinang", "Melaka", "W.P. Kuala Lumpur", "W.P. Labuan",
                                  "W.P. Putrajaya", "Sabah", "Sarawak", "Pahang"} <= states
    assert boundaries.DISTRICTS_PATH.name == "dosm_administrative_2_district.geojson"
    assert not list(boundaries.BOUNDARY_DIR.glob("geoBoundaries*"))
    attribution = boundaries.BOUNDARY_ATTRIBUTION
    assert "Department of Statistics Malaysia (DOSM)" in attribution
    assert "DOSM Open Data Licence" in attribution and "No endorsement by DOSM is implied." in attribution


def test_boundary_lookup_degrades_without_data(monkeypatch, tmp_path):
    monkeypatch.setattr(boundaries, "_districts", None)
    monkeypatch.setattr(boundaries, "DISTRICTS_PATH", tmp_path / "missing.geojson")
    assert boundaries.lookup(101.5, 3.5) == (None, None)


# ---------------------------------------------------------------------------
# DEM providers (offline)
# ---------------------------------------------------------------------------
def test_dem_grid_validation():
    def grid(lons=np.arange(5.0), lats=np.arange(4.0), z=np.zeros((4, 5)), info=None):
        return DemGrid(lons=lons, lats=lats, z=z, info=dict(SYNTH_INFO) if info is None else info)

    grid().validate()
    for bad in (grid(lons=np.arange(5.0)[::-1]), grid(z=np.zeros((5, 4))), grid(info={}),
                grid(lons=np.array([0.0, 1.0, 2.0, 4.0, 5.0]))):
        with pytest.raises(ValueError):
            bad.validate()


def test_decimate_block_means():
    lons, lats = np.arange(101.0) / 3600, np.arange(81.0) / 3600
    z = np.add.outer(np.arange(81.0), np.arange(101.0))
    z[0, 0] = np.nan
    lo, la, zb = dem.decimate(lons, lats, z, 2000)
    assert zb.size <= 2000 and zb.shape == (la.size, lo.size)
    k = round((lo[1] - lo[0]) * 3600)
    assert k >= 2
    assert np.allclose(np.diff(lo), np.diff(lo).mean()) and np.allclose(np.diff(la), np.diff(la).mean())
    # each block mean equals the mean of its source cells (nanmean ignores the hole)
    r0 = (81 % k) // 2
    c0 = (101 % k) // 2
    assert zb[1, 1] == pytest.approx(np.nanmean(z[r0 + k:r0 + 2 * k, c0 + k:c0 + 2 * k]))
    assert np.isfinite(zb).all()
    same = dem.decimate(lons, lats, z, 10**6)
    assert same[2] is z


def test_copernicus_tile_name():
    assert dem.copernicus_tile_name(3, 101) == "Copernicus_DSM_COG_10_N03_00_E101_00_DEM"
    assert dem.copernicus_tile_name(6, 100) == "Copernicus_DSM_COG_10_N06_00_E100_00_DEM"


def _write_tile(root: Path, lat_floor: int, lon_floor: int, rows: slice, cols: slice, fn):
    """A partial Copernicus-style tile: 1" posts, pixel-is-point origin at
    (lon - 0.5 px, lat_top + 0.5 px), only rows/cols of the full 3600x3600 grid present."""
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import Affine

    n = 3600
    name = dem.copernicus_tile_name(lat_floor, lon_floor)
    (root / name).mkdir(parents=True, exist_ok=True)
    r = np.arange(rows.start, rows.stop)
    c = np.arange(cols.start, cols.stop)
    lat = lat_floor + 1 - r / n
    lon = lon_floor + c / n
    data = fn(*np.meshgrid(lon, lat)).astype("float32")
    t = Affine(1 / n, 0, lon_floor + (cols.start - 0.5) / n,
               0, -1 / n, lat_floor + 1 + (0.5 - rows.start) / n)
    with rasterio.open(root / name / f"{name}.tif", "w", driver="GTiff", width=data.shape[1],
                       height=data.shape[0], count=1, dtype="float32", crs="EPSG:4326",
                       transform=t) as dst:
        dst.write(data, 1)


def test_copernicus_mosaic_across_tiles_with_missing_tile(tmp_path):
    fn = lambda lon, lat: 1000.0 * (lon - 100) + 100.0 * (lat - 3)  # noqa: E731
    n = 3600
    # bbox straddles lon 101 and lat 4: four tiles, the NE one (N04/E101) is "ocean" (absent).
    bbox = (100.99, 3.99, 101.01, 4.01)
    _write_tile(tmp_path, 3, 100, slice(0, 60), slice(n - 60, n), fn)       # SW
    _write_tile(tmp_path, 3, 101, slice(0, 60), slice(0, 60), fn)           # SE
    _write_tile(tmp_path, 4, 100, slice(n - 60, n), slice(n - 60, n), fn)   # NW
    s = make_settings(tmp_path, copernicus_base_url=str(tmp_path))
    g = dem.fetch_copernicus(bbox, s)
    g.validate()
    assert g.info["provider"] == "copernicus" and g.info["vertical_datum"] == "EGM2008"
    assert g.info["epoch"] == "December 2010 – January 2015 (TanDEM-X acquisitions)"
    assert g.info["attribution"].startswith("Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014")
    assert g.info["disclaimer"] == dem.COPERNICUS_DISCLAIMER
    assert g.info["sends_coordinates_to_third_party"] is False
    LONS, LATS = np.meshgrid(g.lons, g.lats)
    ne = (LONS >= 101.0) & (LATS > 4.0)
    assert np.isnan(g.z[ne]).all()
    assert np.allclose(g.z[~ne], fn(LONS[~ne], LATS[~ne]), atol=1e-3)
    # posts exactly on lat 4.0 belong to the N03 tile (its top row), not N04
    row = int(np.argmin(np.abs(g.lats - 4.0)))
    assert np.isfinite(g.z[row]).all()


def test_copernicus_decimates_to_max_cells(tmp_path):
    fn = lambda lon, lat: 5.0 + 0 * lon  # noqa: E731
    _write_tile(tmp_path, 3, 101, slice(0, 400), slice(0, 400), fn)
    s = make_settings(tmp_path, copernicus_base_url=str(tmp_path), max_grid_cells=5000)
    g = dem.fetch_copernicus((101.0, 3.9, 101.1, 4.0), s)
    assert g.z.size <= 5000
    assert np.nanmax(np.abs(g.z - 5.0)) < 1e-6


def test_copernicus_unreachable_raises_dem_unavailable(tmp_path, monkeypatch):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.errors import RasterioIOError

    def boom(*a, **k):
        raise RasterioIOError("CURL error: Could not resolve host: copernicus-dem-30m.s3.amazonaws.com")
    monkeypatch.setattr(rasterio, "open", boom)
    with pytest.raises(ScreeningError) as e:
        dem.fetch_copernicus((101.0, 3.0, 101.01, 3.01), make_settings(tmp_path))
    assert e.value.code == "dem_unavailable" and "could not be reached" in e.value.message


def test_copernicus_sea_zeros_are_no_data(tmp_path):
    """GEO-1: the AWS tiles have no nodata value and store sea as exactly 0.0 m. An offshore
    polygon must not screen as flat Class I land; coastal cells must count as gaps."""
    fn = lambda lon, lat: np.where(lon < 101.5, 0.0, 5.0 + 100.0 * (lon - 101.5))  # noqa: E731
    _write_tile(tmp_path, 3, 101, slice(1600, 2000), slice(1500, 2000), fn)
    s = make_settings(tmp_path, copernicus_base_url=str(tmp_path))
    g = dem.fetch_copernicus((101.45, 3.45, 101.54, 3.54), s)
    LONS = np.meshgrid(g.lons, g.lats)[0]
    assert np.isnan(g.z[LONS < 101.5]).all() and np.isfinite(g.z[LONS > 101.5]).all()

    offshore = polygon_pm("Offshore", rect(101.46, 3.48, 1000, 1000))
    with pytest.raises(ScreeningError) as e:
        screen(tmp_path / "sea", offshore, dem.fetch_copernicus, settings=s)
    assert e.value.code == "no_dem_coverage" and "offshore" in e.value.message
    coast = polygon_pm("Coast", rect(*offset(101.5, 3.48, -400, 0), 1000, 1000))
    result, _ = screen(tmp_path / "coast", coast, dem.fetch_copernicus, settings=s)
    assert "dem_nodata" in codes(result)
    assert result["sites"][0]["elev_min_m"] > 0


def test_copernicus_missing_tile_rules():
    """Over HTTP only a 404 means "tile not published" (ocean); GDAL's "does not exist in the
    file system" (e.g. after a timeout) must report the service as unreachable (R2)."""
    from rasterio.errors import RasterioIOError

    url = "https://copernicus-dem-30m.s3.amazonaws.com/x/x.tif"
    assert dem._is_missing(RasterioIOError("HTTP response code: 404"), url)
    assert not dem._is_missing(RasterioIOError(f"'/vsicurl/{url}' does not exist in the file system"), url)
    assert not dem._is_missing(RasterioIOError("CURL error: Operation timed out"), url)
    assert dem._is_missing(RasterioIOError("/data/x.tif: No such file or directory"), "/data/x.tif")


class _TileServer:
    """Range-capable HTTP server for local tiles whose answers can be switched to 500."""

    def __init__(self, root: Path):
        import http.server
        import re
        import threading

        server = self
        self.mode = "ok"
        self.requests = 0

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _serve(self, head: bool):
                server.requests += 1
                if server.mode != "ok":
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                path = root / self.path.lstrip("/").split("?")[0]
                if not path.is_file():
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = path.read_bytes()
                a, b = 0, len(data) - 1
                m = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range") or "")
                if m:
                    a, b = int(m.group(1)), min(int(m.group(2) or b), b)
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {a}-{b}/{len(data)}")
                else:
                    self.send_response(200)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(b - a + 1))
                self.end_headers()
                if not head:
                    self.wfile.write(data[a:b + 1])

            def do_GET(self):
                self._serve(False)

            def do_HEAD(self):
                self._serve(True)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_copernicus_recovers_after_a_transient_http_error(tmp_path, monkeypatch):
    """R2: GDAL caches /vsicurl failures for the life of the process. After one 500 the next
    job must read the tile again (not fail in 0 s, not be told its site is offshore)."""
    pytest.importorskip("rasterio")
    fn = lambda lon, lat: 50.0 + 0 * lon  # noqa: E731
    _write_tile(tmp_path / "tiles", 3, 101, slice(1700, 1900), slice(1700, 1900), fn)
    srv = _TileServer(tmp_path / "tiles")
    monkeypatch.setitem(dem.COPERNICUS_GDAL_ENV, "GDAL_HTTP_MAX_RETRY", 0)   # keep the test fast
    s = make_settings(tmp_path, copernicus_base_url=srv.url)
    bbox = (101.49, 3.49, 101.51, 3.51)
    try:
        srv.mode = "500"
        with pytest.raises(ScreeningError) as e:
            dem.fetch_copernicus(bbox, s)
        assert e.value.code == "dem_unavailable"
        srv.mode = "ok"
        before = srv.requests
        g = dem.fetch_copernicus(bbox, s)
        assert srv.requests > before                      # asked the server again
        assert np.nanmax(np.abs(g.z - 50.0)) < 1e-6 and np.isfinite(g.z).all()
    finally:
        srv.close()


def test_copernicus_http_limits_bound_a_stalled_endpoint():
    """R12: one worker runs jobs in turn, so a blackholed endpoint must fail in well under a
    minute per tile: (retries + 1) attempts x the stall timeout."""
    env = dem.COPERNICUS_GDAL_ENV
    assert env["GDAL_HTTP_CONNECTTIMEOUT"] <= 10
    assert env["GDAL_HTTP_LOW_SPEED_LIMIT"] >= 1
    assert (env["GDAL_HTTP_MAX_RETRY"] + 1) * env["GDAL_HTTP_LOW_SPEED_TIME"] <= 45


def test_rasterio_import_failure_names_the_cause(monkeypatch):
    """R1: a missing shared library (as in the slim Docker image) must not be reported as
    "rasterio is required"."""
    import builtins

    real_import = builtins.__import__

    def failing(name, *args, **kwargs):
        if name == "rasterio" or name.startswith("rasterio."):
            raise ImportError("libexpat.so.1: cannot open shared object file: No such file or directory")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing)
    with pytest.raises(RuntimeError) as e:
        dem._import_rasterio()
    assert "libexpat.so.1" in str(e.value)


def _old_geotiff_window(path, bbox, max_cells):
    """The previous fetch_geotiff: read the whole window, flip, then decimate()."""
    import rasterio
    from rasterio.windows import Window

    min_lon, min_lat, max_lon, max_lat = bbox
    with rasterio.open(path) as src:
        t = src.transform
        cols = sorted(((min_lon - t.c) / t.a - 0.5, (max_lon - t.c) / t.a - 0.5))
        rows = sorted(((max_lat - t.f) / t.e - 0.5, (min_lat - t.f) / t.e - 0.5))
        c_lo, c_hi = max(0, math.floor(cols[0])), min(src.width - 1, math.ceil(cols[1]))
        r_lo, r_hi = max(0, math.floor(rows[0])), min(src.height - 1, math.ceil(rows[1]))
        data = src.read(1, window=Window(c_lo, r_lo, c_hi - c_lo + 1, r_hi - r_lo + 1),
                        out_dtype="float64", masked=True)
        z = np.ma.filled(data, np.nan)
        lons = t.c + (np.arange(c_lo, c_hi + 1) + 0.5) * t.a
        lats = t.f + (np.arange(r_lo, r_hi + 1) + 0.5) * t.e
    lats, z = lats[::-1], z[::-1, :]
    return dem.decimate(lons, lats, np.ascontiguousarray(z), max_cells)


def test_geotiff_large_window_is_block_averaged_strip_by_strip(tmp_path, monkeypatch):
    """GEO-6: a high-resolution DTM over a large site is block-averaged while reading, giving
    the same grid as before without holding the full-resolution window in memory."""
    rasterio = pytest.importorskip("rasterio")
    import tracemalloc

    from rasterio.transform import from_origin

    res = 1 / 36000                                    # ~3 m cells
    width, height = 1501, 1203
    west, north = 101.45, 3.55
    rng = np.random.default_rng(1)
    data = rng.normal(100.0, 5.0, (height, width)).astype("float32")
    data[100:140, 200:260] = -9999                     # nodata patch (some whole blocks)
    data[700, :] = np.nan                              # NaN without nodata
    path = tmp_path / "dtm.tif"
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(west, north, res, res), nodata=-9999,
                       tiled=True, blockxsize=256, blockysize=256) as dst:
        dst.write(data, 1)
    bbox = (west + 0.0005, north - 0.033, west + 0.041, north - 0.0005)
    s = make_settings(tmp_path, dem_provider="geotiff", dem_geotiff_path=str(path), max_grid_cells=20_000)
    monkeypatch.setattr(dem, "GEOTIFF_STRIP_CELLS", 40_000)
    tracemalloc.start()
    try:
        g = dem.fetch_dem(bbox, s)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    g.validate()
    lons, lats, z = _old_geotiff_window(path, bbox, 20_000)
    assert g.z.shape == z.shape and g.z.size <= 20_000
    assert np.allclose(g.lons, lons, rtol=0, atol=1e-12) and np.allclose(g.lats, lats, rtol=0, atol=1e-12)
    assert np.allclose(g.z, z, equal_nan=True, atol=1e-9)
    assert np.isnan(g.z).any()
    window_bytes = 8 * (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) / res / res
    assert peak < window_bytes / 3, (peak, window_bytes)


def test_geotiff_provider(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    res = 1 / 3600
    width, height = 200, 150
    west, north = 101.45, 3.55
    lon = west + (np.arange(width) + 0.5) * res
    lat = north - (np.arange(height) + 0.5) * res
    data = (10 + 1000 * (lon[None, :] - west) + 500 * (north - lat[:, None])).astype("float32")
    data[10:15, 50:55] = -9999                                    # inside the requested bbox
    path = tmp_path / "dem.tif"
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1,
                       dtype="float32", crs="EPSG:4326", transform=from_origin(west, north, res, res),
                       nodata=-9999) as dst:
        dst.write(data, 1)
    s = make_settings(tmp_path, dem_provider="geotiff", dem_geotiff_path=str(path),
                      extra={"dem_geotiff_info": {"name": "Test LiDAR DTM", "epoch": "2024"}})
    g = dem.fetch_dem((101.46, 3.52, 101.48, 3.549), s)
    g.validate()
    assert g.info["name"] == "Test LiDAR DTM" and g.info["epoch"] == "2024"
    assert g.info["nominal_resolution_m"] == 31
    assert g.lats[0] < g.lats[-1] and g.lons[0] < g.lons[-1]
    assert g.lons[0] <= 101.46 and g.lons[-1] >= 101.48 and g.lats[0] <= 3.52 and g.lats[-1] >= 3.549
    LONS, LATS = np.meshgrid(g.lons, g.lats)
    expected = 10 + 1000 * (LONS - west) + 500 * (north - LATS)
    finite = np.isfinite(g.z)
    assert np.allclose(g.z[finite], expected[finite], atol=1e-3)
    assert (~finite).sum() == 25                                  # nodata block -> NaN
    assert g.info["sends_coordinates_to_third_party"] is False and g.info["disclaimer"] is None


def test_geotiff_outside_raster_has_no_coverage(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    path = tmp_path / "dem.tif"
    with rasterio.open(path, "w", driver="GTiff", width=10, height=10, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(100.0, 5.0, 0.001, 0.001)) as dst:
        dst.write(np.ones((10, 10), dtype="float32"), 1)
    s = make_settings(tmp_path, dem_provider="geotiff", dem_geotiff_path=str(path))
    with pytest.raises(ScreeningError) as e:
        dem.fetch_dem((101.0, 3.0, 101.01, 3.01), s)
    assert e.value.code == "no_dem_coverage"


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _FakeSession:
    def __init__(self, script):
        self.script = list(script)      # list of callables(payload) -> _Resp | Exception
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        step = self.script.pop(0) if self.script else (lambda p: _ok(p))
        out = step(json)
        if isinstance(out, Exception):
            raise out
        return out


def _ok(payload):
    locs = payload["locations"].split("|")
    return _Resp(200, {"status": "OK", "results": [{"elevation": 12.5} for _ in locs]})


def test_opentopodata_batches_throttles_and_retries(tmp_path):
    sleeps: list[float] = []
    session = _FakeSession([_ok, lambda p: _Resp(429), _ok])
    s = make_settings(tmp_path, dem_provider="opentopodata", opentopodata_url="https://otd.example/v1/")
    g = dem.fetch_opentopodata((101.50, 3.50, 101.52, 3.515), s, session=session, sleep=sleeps.append)
    g.validate()
    n = g.z.size
    assert n <= dem.OTD_MAX_POINTS
    assert all(len(j["locations"].split("|")) <= dem.OTD_BATCH for _, j in session.calls)
    assert all(url == "https://otd.example/v1/srtm30m" for url, _ in session.calls)
    batches = math.ceil(n / dem.OTD_BATCH)
    assert len(session.calls) == batches + 1                       # one retry after the 429
    assert sleeps.count(dem.OTD_RETRY_WAIT_S) == 1
    assert sleeps.count(dem.OTD_CALL_INTERVAL_S) == batches - 1
    assert np.all(g.z == 12.5)
    assert g.info["epoch"] == "11–22 February 2000" and g.info["vertical_datum"] == "EGM96"
    assert g.info["sends_coordinates_to_third_party"] is True and g.info["disclaimer"] is None


def test_opentopodata_null_elevations_become_nan(tmp_path):
    def some_null(payload):
        locs = payload["locations"].split("|")
        return _Resp(200, {"status": "OK", "results": [{"elevation": None if i % 2 else 3.0}
                                                        for i in range(len(locs))]})
    session = _FakeSession([some_null] * 20)
    g = dem.fetch_opentopodata((101.50, 3.50, 101.51, 3.51), make_settings(tmp_path),
                               session=session, sleep=lambda s: None)
    assert np.isnan(g.z).any() and (g.z[np.isfinite(g.z)] == 3.0).all()


def test_opentopodata_failure_is_dem_unavailable(tmp_path):
    import requests

    session = _FakeSession([lambda p: requests.ConnectionError("down"), lambda p: _Resp(503)])
    with pytest.raises(ScreeningError) as e:
        dem.fetch_opentopodata((101.50, 3.50, 101.51, 3.51), make_settings(tmp_path),
                               session=session, sleep=lambda s: None)
    assert e.value.code == "dem_unavailable" and "could not be reached" in e.value.message
    assert len(session.calls) == 2


def test_unknown_provider_is_a_config_error(tmp_path):
    with pytest.raises(ValueError):
        dem.fetch_dem((101.0, 3.0, 101.01, 3.01), make_settings(tmp_path, dem_provider="nope"))


# ---------------------------------------------------------------------------
# network (opt-in): RUN_NETWORK_TESTS=1 CURL_CA_BUNDLE=... pytest -m network
# ---------------------------------------------------------------------------
@pytest.mark.network
@pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1", reason="set RUN_NETWORK_TESTS=1")
def test_copernicus_on_kedah_fixture(tmp_path):
    s = make_settings(tmp_path, dem_provider="copernicus")
    out = tmp_path / "out"
    result = run_screening(FIXTURES / "flat_site_kedah.kml", out, s,
                           {"report_id": "net", "scheme": "lss", "input_filename": "flat_site_kedah.kml"})
    assert result["dem"]["provider"] == "copernicus"
    assert result["dem"]["disclaimer"] == dem.COPERNICUS_DISCLAIMER
    assert result["dem"]["sends_coordinates_to_third_party"] is False
    assert result["location"] == {**result["location"], "state": "Kedah", "district": "Kota Setar"}
    assert {"all_class_i", "indicative_capacity", "eia_area_items", "route_grade"} <= set(codes(result))
    site = result["sites"][0]
    assert -5 < site["elev_min_m"] <= site["elev_max_m"] < 30          # coastal paddy plain
    assert site["kpkt_pct"]["I"] > 95 and site["cells"] > 300
    assert result["routes"][0]["length_km"] == pytest.approx(2.03, abs=0.02)
    assert all((out / f).stat().st_size > 20_000 for f in FIGURE_FILES)
    _strict_json(out / "result.json")


@pytest.mark.parametrize("provider", ["copernicus", "opentopodata"])
def test_figure_footer_does_not_overlap_axis_labels(provider):
    """The layout keeps the axis label above the (one- or two-line) footer stamp, also with a
    colour bar and an equal-aspect map, as on the elevation figure."""
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize

    from app.terrain import figures

    stamp = flags.figure_stamp({"provider": provider, "name": "DEM", "epoch": "2000"})
    fig = figures._new_figure((10.3, 7.0))
    ax = fig.add_subplot(1, 1, 1)
    ax.set_aspect("equal")
    ax.set_xlim(0, 1.5)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Easting (km)", fontsize=8.5)
    fig.colorbar(ScalarMappable(norm=Normalize(0, 1), cmap=figures.ELEV_CMAP), ax=ax, extend="both")
    figures._footer(fig, stamp)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    footer_top = max(t.get_window_extent(renderer).y1 for t in fig.texts)
    assert ax.xaxis.label.get_window_extent(renderer).y0 > footer_top + 5      # pixels
