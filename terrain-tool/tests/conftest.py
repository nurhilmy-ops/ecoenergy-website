"""Shared fixtures for the web-app tests.

The terrain engine and report renderers are replaced by fakes (``fake_engine``)
so these tests never touch the network or depend on app.terrain / app.reports.
Nothing here is autouse: other test modules are unaffected.
"""
from __future__ import annotations

import json
import re
import struct
import sys
import types
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import db  # noqa: E402

FIGURES = ("1_site_layout.png", "2_elevation.png", "3_slope_classes.png", "4_profiles.png")


def pytest_configure(config):
    config.addinivalue_line("markers", "network: needs internet (opt-in with RUN_NETWORK_TESTS=1)")

SAMPLE_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>Parcel A</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
    101.500,2.900,0 101.510,2.900,0 101.510,2.910,0 101.500,2.910,0 101.500,2.900,0
  </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  <Placemark><name>Cable route</name><LineString><coordinates>
    101.505,2.905,0 101.520,2.915,0
  </coordinates></LineString></Placemark>
</Document></kml>
"""


def tiny_png() -> bytes:
    """A valid 1x1 RGB PNG."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00\xd4\xa2\x3a")) \
        + chunk(b"IEND", b"")


def fake_result(meta: dict) -> dict:
    """Minimal result dict following the result.json schema (schema_version 1)."""
    return {
        "schema_version": 1,
        "meta": {**meta, "input_sha256": "0" * 64},
        "dem": {
            "provider": "copernicus", "name": "Copernicus DEM GLO-30",
            "model_type": "DSM (surface: includes tree canopy and buildings)",
            "epoch": "December 2010 – January 2015 (TanDEM-X acquisitions)", "vertical_datum": "EGM2008",
            "nominal_resolution_m": 30, "grid_spacing_m": 30.7, "cells_analysed": 1234,
            "nodata_pct": 0.0, "attribution": "Fake DEM attribution © DLR e.V. / ESA",
            # Added to schema_version 1 later; templates read them with .get().
            "disclaimer": ("The organisations in charge of the Copernicus programme by law or by delegation "
                           "do not incur any liability for any use of the Copernicus WorldDEM-30"),
            "sends_coordinates_to_third_party": False,
        },
        "location": {
            "centroid_lon": 101.505, "centroid_lat": 2.905, "state": "Selangor", "district": "Kuala Langat",
            "utm_epsg": "EPSG:32647", "boundary_attribution": "Fake boundaries (DOSM)",
        },
        "totals": {"polygon_count": 1, "line_count": 1, "point_count": 0, "total_area_ha": 123.4,
                   "total_line_km": 1.9},
        "sites": [{
            "name": "Parcel A", "area_ha": 123.4, "perimeter_m": 4400.0, "centroid": [101.505, 2.905],
            "elev_min_m": 12.0, "elev_max_m": 47.0, "elev_mean_m": 25.5, "relief_m": 35.0,
            "slope_mean_deg": 3.2, "slope_p90_deg": 8.1, "slope_max_deg": 17.6,
            "kpkt_pct": {"I": 96.5, "II": 3.5, "III": 0.0, "IV": 0.0},
            "slope_bins_pct": {"0-2": 40.0, "2-5": 30.0, "5-10": 20.0, "10-15": 6.5, "15-25": 3.5,
                               "25-35": 0.0, ">35": 0.0},
            "cells": 1200,
        }],
        "kpkt_overall_pct": {"I": 96.5, "II": 3.5, "III": 0.0, "IV": 0.0},
        "routes": [{"name": "Cable route", "length_km": 1.9, "elev_min_m": 10.0, "elev_max_m": 30.0,
                    "total_ascent_m": 22.0, "max_grade_pct": 6.5}],
        "points": [],
        "contour_interval_m": 5.0,
        "flags": [
            {"level": "caution", "code": "kpkt_class2", "title": "Some Class II slopes",
             "detail": "3.5% of the site is between 15° and 25°.", "source": "KPKT hillside guidelines"},
            {"level": "warning", "code": "fake_warning", "title": "Fake warning flag",
             "detail": "Shown to test styling.", "source": None},
        ],
        "followups": [{"title": "Topographic survey", "detail": "Commission a ground survey before layout."}],
        "caveats": ["Desktop screening only — not a survey."],
        "figures": [{"file": f, "title": f"Figure {i + 1}", "caption": f"Caption for {f}"}
                    for i, f in enumerate(FIGURES)],
    }


class FakeScreeningError(Exception):
    def __init__(self, message: str, code: str = "screening_error"):
        super().__init__(message)
        self.code = code


@pytest.fixture
def fake_engine(monkeypatch):
    """Install fake ``app.terrain`` / ``app.reports`` modules. ``state.run_behaviour`` can be
    set to "screening_error" or "crash" to simulate failures."""
    state = SimpleNamespace(run_behaviour=None, run_calls=[], validate_calls=[], build_calls=[])
    png = tiny_png()

    def validate_upload(path, settings, original_filename):
        state.validate_calls.append(original_filename)
        data = Path(path).read_bytes()
        if b"<kml" not in data and not data.startswith(b"PK"):
            raise FakeScreeningError("We couldn't find any site boundaries in that file.", code="no_geometry")
        return SimpleNamespace(features=[], bbox=(101.5, 2.9, 101.52, 2.915), extent_km=2.0,
                               source_filename=original_filename)

    def run_screening(path, out_dir, settings, meta):
        state.run_calls.append(dict(meta))
        if state.run_behaviour == "screening_error":
            raise FakeScreeningError("The elevation data service could not be reached. Please try again later.",
                                     code="dem_unavailable")
        if state.run_behaviour == "crash":
            raise RuntimeError("simulated engine crash")
        out_dir = Path(out_dir)
        for name in FIGURES:
            (out_dir / name).write_bytes(png)
        result = fake_result(meta)
        (out_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (out_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")
        return result

    def build_reports(result, out_dir, settings):
        state.build_calls.append(result["meta"]["report_id"])
        pdf, docx = Path(out_dir) / "report.pdf", Path(out_dir) / "report.docx"
        pdf.write_bytes(b"%PDF-1.4\n% fake report\n%%EOF\n")
        docx.write_bytes(b"PK\x03\x04 fake docx")
        return {"pdf": pdf, "docx": docx}

    terrain = types.ModuleType("app.terrain")
    terrain.ScreeningError = FakeScreeningError
    terrain.validate_upload = validate_upload
    terrain.run_screening = run_screening
    reports = types.ModuleType("app.reports")
    reports.build_reports = build_reports
    monkeypatch.setitem(sys.modules, "app.terrain", terrain)
    monkeypatch.setitem(sys.modules, "app.reports", reports)
    return state


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        data_dir=tmp_path / "data", app_env="development", base_url="http://testserver",
        secret_key="test-secret-key", mail_backend="outbox", worker_inline=False,
        admin_user="admin", admin_password="correct horse battery", trust_proxy_headers=False,
        turnstile_site_key="", turnstile_secret_key="", token_ttl_hours=72, token_max_uses=5,
        session_ttl_hours=24, retention_days=30, unverified_purge_days=7,
        rate_link_per_email_hour=3, rate_link_per_ip_hour=10, rate_jobs_per_email_day=3,
        rate_jobs_per_ip_day=10, max_upload_mb=5.0, worker_poll_seconds=0.05,
    )
    base.update(overrides)
    return Settings.from_env(overrides=base, env_file=tmp_path / "missing.env")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def web_app(settings, fake_engine):
    from app.main import create_app
    return create_app(settings)


@pytest.fixture
def client(web_app):
    with TestClient(web_app) as c:
        yield c


def hidden(html: str, name: str) -> str:
    m = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    assert m, f"hidden field {name!r} not found"
    return m.group(1)


def rows(settings: Settings, sql: str, params: tuple = ()) -> list[dict]:
    with db(settings.db_path) as conn:
        return [dict(r) for r in conn.execute(sql, params)]


class Flow:
    """Drives the visitor flow through a TestClient."""

    hidden = staticmethod(hidden)
    sample_kml = SAMPLE_KML

    def __init__(self, client: TestClient, settings: Settings):
        self.client = client
        self.settings = settings

    def request_link(self, email: str, newsletter: bool = False, **extra):
        data = {"email": email, **extra}
        if newsletter:
            data["newsletter"] = "yes"
        return self.client.post("/request-link", data=data)

    def mails(self, to: str | None = None) -> list[dict]:
        if to:
            return rows(self.settings, "SELECT * FROM outbox WHERE to_addr = ? ORDER BY id", (to,))
        return rows(self.settings, "SELECT * FROM outbox ORDER BY id")

    def token_from(self, mail: dict) -> str:
        m = re.search(r"/start\?t=([A-Za-z0-9_\-]+)", mail["text_body"])
        assert m, "no magic link in email"
        return m.group(1)

    def latest_token(self, to: str) -> str:
        return self.token_from(self.mails(to)[-1])

    def confirm(self, token: str):
        page = self.client.get(f"/start?t={token}")
        assert page.status_code == 200, page.text
        return self.client.post("/start", data={"t": hidden(page.text, "t"), "pre": hidden(page.text, "pre")},
                                follow_redirects=False)

    def login(self, email: str, newsletter: bool = False) -> None:
        self.request_link(email, newsletter=newsletter)
        resp = self.confirm(self.latest_token(email))
        assert resp.status_code == 303, resp.text

    def csrf(self) -> str:
        page = self.client.get("/upload")
        assert page.status_code == 200, page.text
        return hidden(page.text, "csrf")

    def upload(self, content: bytes = SAMPLE_KML, filename: str = "site.kml", csrf: str | None = None,
               **fields):
        data = {"csrf": self.csrf() if csrf is None else csrf, **fields}
        return self.client.post("/upload", data=data,
                                files={"kml_file": (filename, content, "application/vnd.google-earth.kml+xml")},
                                follow_redirects=False)

    def upload_job(self, **fields) -> str:
        resp = self.upload(**fields)
        assert resp.status_code == 303, resp.text
        return resp.headers["location"].rsplit("/", 1)[-1]


@pytest.fixture
def flow(client, settings) -> Flow:
    return Flow(client, settings)


@pytest.fixture
def make_flow(web_app, settings):
    """Factory for additional visitors (separate cookie jars) on the same app."""
    clients: list[TestClient] = []

    def factory() -> Flow:
        c = TestClient(web_app)
        clients.append(c)
        return Flow(c, settings)

    yield factory
    for c in clients:
        c.close()


@pytest.fixture
def query(settings):
    """query(sql, params=()) -> list of row dicts against the test database."""
    return lambda sql, params=(): rows(settings, sql, params)


@pytest.fixture
def app_factory(tmp_path, fake_engine):
    """Build an extra app with Settings overrides: app_factory("name", **overrides) -> Flow."""
    from app.main import create_app

    clients: list[TestClient] = []

    def factory(name: str = "alt", **overrides) -> Flow:
        s = make_settings(tmp_path / name, **overrides)
        c = TestClient(create_app(s))
        clients.append(c)
        return Flow(c, s)

    yield factory
    for c in clients:
        c.close()
