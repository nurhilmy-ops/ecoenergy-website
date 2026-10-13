"""End-to-end integration: real web app + real terrain engine + real report renderers.

The other web tests replace ``app.terrain`` / ``app.reports`` with fakes; these run the
genuine packages through HTTP. Elevations come from a small synthetic GeoTIFF read by
the engine's own ``geotiff`` provider, so the test is offline and deterministic.
"""
from __future__ import annotations

import io
import json
import math
import re
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pyproj import Geod

from app import jobs
from app.main import create_app
from conftest import Flow, make_settings, rows  # helpers shared with the web tests

FIXTURES = Path(__file__).resolve().parent / "fixtures"
KEDAH = FIXTURES / "flat_site_kedah.kml"
PERAK = FIXTURES / "fpv_pond_perak.kml"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
GEOD = Geod(ellps="WGS84")

# Key sets of result.json schema_version 1 (docs/ARCHITECTURE.md).
TOP_KEYS = {"schema_version", "meta", "dem", "location", "totals", "sites", "kpkt_overall_pct",
            "routes", "points", "contour_interval_m", "flags", "followups", "caveats", "figures"}
META_KEYS = {"report_id", "generated_at", "site_label", "scheme", "stage", "input_filename",
             "input_sha256"}
DEM_KEYS = {"provider", "name", "model_type", "epoch", "vertical_datum", "nominal_resolution_m",
            "grid_spacing_m", "cells_analysed", "nodata_pct", "attribution"}
LOCATION_KEYS = {"centroid_lon", "centroid_lat", "state", "district", "utm_epsg", "boundary_attribution"}
TOTALS_KEYS = {"polygon_count", "line_count", "point_count", "total_area_ha", "total_line_km"}
SITE_KEYS = {"name", "area_ha", "perimeter_m", "centroid", "elev_min_m", "elev_max_m", "elev_mean_m",
             "relief_m", "slope_mean_deg", "slope_p90_deg", "slope_max_deg", "kpkt_pct",
             "slope_bins_pct", "cells"}
ROUTE_KEYS = {"name", "length_km", "elev_min_m", "elev_max_m", "total_ascent_m", "max_grade_pct"}
POINT_KEYS = {"name", "lon", "lat", "elev_m"}
KPKT = ("I", "II", "III", "IV")
BINS = ("0-2", "2-5", "5-10", "10-15", "15-25", "25-35", ">35")
FIGURES = ("1_site_layout.png", "2_elevation.png", "3_slope_classes.png", "4_profiles.png")


def write_geotiff(path: Path, bbox: tuple[float, float, float, float], elevation) -> Path:
    """EPSG:4326 GeoTIFF at 1 arc-second over bbox; elevation(x_m, y_m) is in metres east /
    north of the south-west corner."""
    import rasterio
    from rasterio.transform import from_origin

    res = 1 / 3600
    min_lon, min_lat, max_lon, max_lat = bbox
    width = math.ceil((max_lon - min_lon) / res)
    height = math.ceil((max_lat - min_lat) / res)
    mid_lat = (min_lat + max_lat) / 2
    m_per_deg_x = GEOD.inv(min_lon, mid_lat, min_lon + 1, mid_lat)[2]
    m_per_deg_y = GEOD.inv(min_lon, mid_lat - 0.5, min_lon, mid_lat + 0.5)[2]
    lons = min_lon + (np.arange(width) + 0.5) * res
    lats = max_lat - (np.arange(height) + 0.5) * res          # north-up rows
    X, Y = np.meshgrid((lons - min_lon) * m_per_deg_x, (lats - min_lat) * m_per_deg_y)
    z = np.asarray(elevation(X, Y), dtype="float32") * np.ones_like(X, dtype="float32")
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(min_lon, max_lat, res, res)) as dst:
        dst.write(z, 1)
    return path


def fixture_bbox(path: Path, margin_deg: float = 0.05) -> tuple[float, float, float, float]:
    pairs = re.findall(r"(-?\d+\.\d+),(-?\d+\.\d+)", path.read_text(encoding="utf-8"))
    lons = [float(a) for a, _ in pairs]
    lats = [float(b) for _, b in pairs]
    return (min(lons) - margin_deg, min(lats) - margin_deg, max(lons) + margin_deg, max(lats) + margin_deg)


@pytest.fixture
def real_app(tmp_path):
    """Factory: (geotiff path) -> (Flow, settings) on the real app with the inline worker off,
    so the test drives the queue with jobs.run_once()."""
    clients: list[TestClient] = []

    def factory(tif: Path) -> tuple[Flow, object]:
        settings = make_settings(tmp_path, dem_provider="geotiff", dem_geotiff_path=str(tif))
        client = TestClient(create_app(settings))
        clients.append(client)
        return Flow(client, settings), settings

    yield factory
    for c in clients:
        c.close()


def check_contract(result: dict) -> None:
    assert set(result) == TOP_KEYS
    assert result["schema_version"] == 1
    assert set(result["meta"]) == META_KEYS
    assert set(result["dem"]) == DEM_KEYS
    assert set(result["location"]) == LOCATION_KEYS
    assert set(result["totals"]) == TOTALS_KEYS
    for site in result["sites"]:
        assert set(site) == SITE_KEYS
        assert tuple(site["kpkt_pct"]) == KPKT
        assert tuple(site["slope_bins_pct"]) == BINS
        assert sum(site["kpkt_pct"].values()) == pytest.approx(100, abs=0.5)
        assert sum(site["slope_bins_pct"].values()) == pytest.approx(100, abs=0.5)
    for route in result["routes"]:
        assert set(route) == ROUTE_KEYS
    for point in result["points"]:
        assert set(point) == POINT_KEYS
    assert tuple(result["kpkt_overall_pct"]) == KPKT
    for flag in result["flags"]:
        assert set(flag) == {"level", "code", "title", "detail", "source"}
        assert flag["level"] in {"info", "caution", "warning"}
    assert all(set(f) == {"title", "detail"} for f in result["followups"])
    assert all(isinstance(c, str) and c for c in result["caveats"])
    assert [f["file"] for f in result["figures"]] == list(FIGURES)
    # Strict JSON: no NaN / Infinity anywhere.
    json.dumps(result, allow_nan=False)


def run_job(flow: Flow, settings, kml: Path, **fields) -> str:
    flow.login("integration@example.com")
    resp = flow.upload(content=kml.read_bytes(), filename=kml.name, **fields)
    assert resp.status_code == 303, resp.text
    job_id = resp.headers["location"].rsplit("/", 1)[-1]
    assert flow.client.get(f"/api/reports/{job_id}/status").json()["status"] == "queued"
    assert jobs.run_once(settings) is True
    status = flow.client.get(f"/api/reports/{job_id}/status").json()
    assert status == {"status": "done", "error": None}
    return job_id


def test_real_pipeline_through_http(tmp_path, real_app):
    # A plane rising east at 20 degrees: every site cell is KPKT Class II.
    tan20 = math.tan(math.radians(20))
    tif = write_geotiff(tmp_path / "plane.tif", fixture_bbox(KEDAH), lambda x, y: 5.0 + tan20 * x)
    flow, settings = real_app(tif)
    job_id = run_job(flow, settings, KEDAH, scheme="lss", stage="exploring", site_label="Plane test")

    out = jobs.job_dir(settings, job_id)
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    check_contract(result)
    assert result["meta"]["report_id"] == job_id
    assert result["meta"]["scheme"] == "lss" and result["meta"]["site_label"] == "Plane test"
    assert result["dem"]["provider"] == "geotiff"
    assert result["location"]["state"] == "Kedah"
    # Geometry comes from the KML and does not depend on the DEM.
    assert result["totals"]["total_area_ha"] == pytest.approx(42.16, abs=0.3)
    assert result["routes"][0]["length_km"] == pytest.approx(2.03, abs=0.03)
    site = result["sites"][0]
    assert site["slope_mean_deg"] == pytest.approx(20, abs=0.5)
    assert site["kpkt_pct"]["II"] == pytest.approx(100, abs=0.5)
    codes = {f["code"] for f in result["flags"]}
    assert "kpkt_class_ii" in codes and "all_class_i" not in codes

    # Result page renders the real result: site, numbers, flags, figures, downloads.
    page = flow.client.get(f"/reports/{job_id}")
    assert page.status_code == 200
    assert "Lot A paddy" in page.text and "Plane test" in page.text
    assert next(f["title"] for f in result["flags"] if f["code"] == "kpkt_class_ii") in page.text
    for name in FIGURES:
        assert f"/reports/{job_id}/files/{name}" in page.text
        img = flow.client.get(f"/reports/{job_id}/files/{name}")
        assert img.status_code == 200 and img.content.startswith(PNG_MAGIC)
        assert len(img.content) > 20_000            # a real rendered figure, not a stub

    pdf = flow.client.get(f"/reports/{job_id}/download.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf.content))
    assert len(reader.pages) >= 5
    text = "\n".join(p.extract_text() for p in reader.pages)
    assert "Lot A paddy" in text and job_id[:8] in text

    docx = flow.client.get(f"/reports/{job_id}/download.docx")
    assert docx.status_code == 200
    with zipfile.ZipFile(io.BytesIO(docx.content)) as z:
        assert "Lot A paddy" in z.read("word/document.xml").decode("utf-8")

    # Lead summary columns and the report-ready email.
    job = rows(settings, "SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
    assert job["state"] == "Kedah" and job["kpkt_class1_pct"] == pytest.approx(0, abs=0.5)
    assert job["total_area_ha"] == pytest.approx(42.16, abs=0.3)
    ready = flow.mails("integration@example.com")[-1]
    assert "ready" in ready["subject"].lower() and "/start?t=" in ready["text_body"]

    # Delete now removes every file and the derived site fields.
    resp = flow.client.post(f"/reports/{job_id}/delete", data={"csrf": flow.csrf()}, follow_redirects=False)
    assert resp.status_code == 303
    assert not out.exists()
    job = rows(settings, "SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
    assert job["status"] == "deleted" and job["state"] is None and job["total_area_ha"] is None


def test_fpv_scheme_on_flat_water(tmp_path, real_app):
    tif = write_geotiff(tmp_path / "flat.tif", fixture_bbox(PERAK), lambda x, y: 31.0)
    flow, settings = real_app(tif)
    job_id = run_job(flow, settings, PERAK, scheme="fpv")

    result = json.loads((jobs.job_dir(settings, job_id) / "result.json").read_text(encoding="utf-8"))
    check_contract(result)
    site = result["sites"][0]
    assert site["relief_m"] == pytest.approx(0, abs=0.1)
    assert site["kpkt_pct"]["I"] == 100
    codes = {f["code"] for f in result["flags"]}
    assert "fpv_dem_epoch" in codes
    # Ground-mount wording is suppressed for floating solar.
    assert not codes & {"steep_for_ground_pv", "all_class_i"}
    assert any("Bathymetric" in f["title"] for f in result["followups"])
    page = flow.client.get(f"/reports/{job_id}")
    assert page.status_code == 200
    # Flat sites keep one decimal on the page, so a level water surface reads as such.
    assert "31.0–31.0" in page.text


def test_dem_outside_coverage_fails_cleanly(tmp_path, real_app):
    # GeoTIFF over the Perak fixture, upload in Kedah: the job fails with a visitor-safe
    # message instead of fabricating elevations.
    tif = write_geotiff(tmp_path / "elsewhere.tif", fixture_bbox(PERAK), lambda x, y: 31.0)
    flow, settings = real_app(tif)
    flow.login("integration@example.com")
    resp = flow.upload(content=KEDAH.read_bytes(), filename=KEDAH.name)
    job_id = resp.headers["location"].rsplit("/", 1)[-1]
    jobs.run_once(settings)
    status = flow.client.get(f"/api/reports/{job_id}/status").json()
    assert status["status"] == "failed"
    assert status["error"] and status["error"] != jobs.GENERIC_FAILURE
    assert not (jobs.job_dir(settings, job_id) / "report.pdf").exists()
    page = flow.client.get(f"/reports/{job_id}")
    assert page.status_code == 200 and status["error"] in page.text
