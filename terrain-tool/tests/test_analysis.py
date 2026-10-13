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
                            polygon_pm, rect, write)

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
            "grid_spacing_m", "cells_analysed", "nodata_pct", "attribution"}
LOCATION_KEYS = {"centroid_lon", "centroid_lat", "state", "district", "utm_epsg",
                 "boundary_attribution"}
TOTALS_KEYS = {"polygon_count", "line_count", "point_count", "total_area_ha", "total_line_km"}
SITE_KEYS = {"name", "area_ha", "perimeter_m", "centroid", "elev_min_m", "elev_max_m",
             "elev_mean_m", "relief_m", "slope_mean_deg", "slope_p90_deg", "slope_max_deg",
             "kpkt_pct", "slope_bins_pct", "cells"}
KPKT_KEYS = {"I", "II", "III", "IV"}
BIN_KEYS = {"0-2", "2-5", "5-10", "10-15", "15-25", "25-35", ">35"}
ROUTE_KEYS = {"name", "length_km", "elev_min_m", "elev_max_m", "total_ascent_m", "max_grade_pct"}
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


def test_kpkt_overall_is_area_weighted(tmp_path):
    big = rect(LON, LAT, 600, 400)                      # flat: 24 ha
    small = rect(*offset(LON, LAT, 1000, 0), 300, 200)  # 20°: 6 ha
    small_lon0 = small[0][0]
    t = math.tan(math.radians(20))

    def terrain(LONS, LATS, X, Y):
        return np.where(LONS > small_lon0 - 0.0015, 10.0 + t * X, 10.0)

    result, _ = screen(tmp_path, polygon_pm("Big", big) + polygon_pm("Small", small),
                       function_fetcher(terrain))
    a_big, a_small = (s["area_ha"] for s in result["sites"])
    expected_ii = 100.0 * a_small / (a_big + a_small)
    assert result["kpkt_overall_pct"]["II"] == pytest.approx(expected_ii, abs=0.3)
    assert "kpkt_class_ii" in codes(result)


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
                                "total_line_km": result["routes"][0]["length_km"]}
    assert result["location"]["utm_epsg"] == "EPSG:32647"
    assert result["location"]["state"] == "Selangor"
    assert result["dem"]["cells_analysed"] > 0 and result["dem"]["nodata_pct"] == 0.0
    assert result["contour_interval_m"] >= 5.0

    # flags are sorted most severe first and always include the EIA reminder
    order = [{"warning": 0, "caution": 1, "info": 2}[f["level"]] for f in result["flags"]]
    assert order == sorted(order) and "eia_check" in codes(result)

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
    assert "eia_check" not in codes(result)


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
    assert any(f["title"] == "Geotechnical slope assessment" for f in result["followups"])


def test_elevated_terrain_flag(tmp_path):
    result, _ = screen(tmp_path, polygon_pm("Highland", rect(LON, LAT, 300, 300)),
                       plane_fetcher(2.0, base=flags.ELEVATED_TERRAIN_M + 50))
    f = next(f for f in result["flags"] if f["code"] == "elevated_terrain")
    assert f["level"] == "caution" and "local planning authority" in f["detail"]


def test_fpv_flags(tmp_path):
    flat, _ = screen(tmp_path / "flat", polygon_pm("Pond", rect(LON, LAT, 400, 400)),
                     plane_fetcher(0.0, base=31.0), settings=make_settings(tmp_path), scheme="fpv")
    assert "fpv_dem_epoch" in codes(flat) and "fpv_land_inside" not in codes(flat)
    assert "all_class_i" not in codes(flat) and "steep_for_ground_pv" not in codes(flat)
    titles = [f["title"] for f in flat["followups"]]
    fpv_only = {"Bathymetric survey", "Seasonal water-level records", "Bund geotechnical assessment"}
    assert fpv_only <= set(titles)

    hilly, _ = screen(tmp_path / "hilly", polygon_pm("Pond", rect(LON, LAT, 400, 400)),
                      plane_fetcher(8.0), settings=make_settings(tmp_path), scheme="fpv")
    land = next(f for f in hilly["flags"] if f["code"] == "fpv_land_inside")
    assert land["level"] == "caution" and "post-dates" in land["detail"]

    lss, _ = screen(tmp_path / "lss", polygon_pm("Pond", rect(LON, LAT, 400, 400)),
                    plane_fetcher(0.0), settings=make_settings(tmp_path), scheme="lss")
    assert not [c for c in codes(lss) if c.startswith("fpv")]
    assert "Bathymetric survey" not in [f["title"] for f in lss["followups"]]


def test_eia_flag_never_quotes_a_threshold(tmp_path):
    result, _ = screen(tmp_path, polygon_pm("S", rect(LON, LAT, 300, 300)), plane_fetcher(1.0))
    eia = next(f for f in result["flags"] if f["code"] == "eia_check")
    numbers = [w for w in eia["detail"].replace(",", " ").split() if w.replace(".", "").isdigit()]
    assert numbers == [f"{result['totals']['total_area_ha']:.2f}", "2015"]


def test_flag_thresholds_from_numbers_only():
    """Rules read numbers, never names: identical numbers, different names -> same codes."""
    base = {"meta": {"scheme": "lss"}, "dem": {"name": "X", "epoch": "2000", "nodata_pct": 0.0},
            "totals": {"total_area_ha": 10.0}, "routes": []}
    site = {"kpkt_pct": {"I": 100.0, "II": 0.0, "III": 0.0, "IV": 0.0},
            "slope_bins_pct": {"0-2": 100.0, "2-5": 0.0, "5-10": 0.0, "10-15": 0.0, "15-25": 0.0,
                               "25-35": 0.0, ">35": 0.0},
            "relief_m": 3.0, "elev_max_m": 20.0, "slope_p90_deg": 1.0, "cells": 400}
    a = flags.build_flags({**base, "sites": [{**site, "name": "pond FPV steep Class IV hill"}]})
    b = flags.build_flags({**base, "sites": [{**site, "name": "Lot 7"}]})
    assert [f["code"] for f in a] == [f["code"] for f in b] == ["all_class_i", "eia_check"]


def test_figure_stamp():
    stamp = flags.figure_stamp({"name": "Copernicus DEM GLO-30",
                                "epoch": "2011–2015 (TanDEM-X acquisitions)"})
    assert stamp == ("Desktop screening — not a survey · DEM: Copernicus DEM GLO-30 "
                     "(2011–2015, TanDEM-X acquisitions) · EcoEnergy Consultancy")


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
    (100.37, 6.05, "Kedah", "Kota Setar"),
    (101.90, 3.52, "Pahang", "Bentong"),
    (101.08, 4.53, "Perak", "Kinta"),
    (116.07, 5.98, "Sabah", "Kota Kinabalu"),
])
def test_boundary_lookup(lon, lat, state, district):
    assert boundaries.lookup(lon, lat) == (state, district)


def test_boundary_lookup_offshore():
    assert boundaries.lookup(104.5, 2.0) == (None, None)          # South China Sea
    near = boundaries.lookup(100.355, 6.20)                       # ~1–2 km off the Kedah coast
    assert near[0] == "Kedah"


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
    assert g.info["epoch"] == "February 2000" and g.info["vertical_datum"] == "EGM96"


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
    assert result["location"]["state"] == "Kedah"
    site = result["sites"][0]
    assert -5 < site["elev_min_m"] <= site["elev_max_m"] < 30          # coastal paddy plain
    assert site["kpkt_pct"]["I"] > 95 and site["cells"] > 300
    assert result["routes"][0]["length_km"] == pytest.approx(2.03, abs=0.02)
    assert all((out / f).stat().st_size > 20_000 for f in FIGURE_FILES)
    _strict_json(out / "result.json")
