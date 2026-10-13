"""Helpers for the terrain engine tests: KML builders, synthetic DEM fetchers, settings."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from pyproj import Geod

from app.config import Settings
from app.terrain.dem import DemGrid

GEOD = Geod(ellps="WGS84")
FIXTURES = Path(__file__).resolve().parent / "fixtures"
KML22 = "http://www.opengis.net/kml/2.2"

SYNTH_INFO = {
    "provider": "geotiff",
    "name": "Synthetic test DEM",
    "model_type": "DTM (synthetic)",
    "epoch": "test",
    "vertical_datum": "none",
    "nominal_resolution_m": 30,
    "attribution": "Synthetic terrain for tests.",
}


def make_settings(tmp_path: Path | None = None, **overrides) -> Settings:
    """A Settings instance without touching the environment or .env."""
    kw = {"data_dir": tmp_path} if tmp_path is not None else {}
    kw.update(overrides)
    return Settings(**kw)


# ---------------------------------------------------------------------------
# KML builders
# ---------------------------------------------------------------------------
def coords_text(pts, alt: bool = True) -> str:
    return " ".join(f"{x:.7f},{y:.7f}" + (",0" if alt else "") for x, y in pts)


def ring_closed(pts):
    pts = list(pts)
    return pts + [pts[0]]


def polygon_pm(name: str | None, ring, holes=(), prefix: str = "") -> str:
    p = prefix
    n = f"<{p}name>{name}</{p}name>" if name is not None else ""
    inner = "".join(
        f"<{p}innerBoundaryIs><{p}LinearRing><{p}coordinates>{coords_text(ring_closed(h))}"
        f"</{p}coordinates></{p}LinearRing></{p}innerBoundaryIs>" for h in holes)
    return (f"<{p}Placemark>{n}<{p}Polygon><{p}outerBoundaryIs><{p}LinearRing><{p}coordinates>"
            f"{coords_text(ring_closed(ring))}</{p}coordinates></{p}LinearRing></{p}outerBoundaryIs>"
            f"{inner}</{p}Polygon></{p}Placemark>")


def line_pm(name: str | None, pts) -> str:
    n = f"<name>{name}</name>" if name is not None else ""
    return (f"<Placemark>{n}<LineString><tessellate>1</tessellate><coordinates>"
            f"{coords_text(pts)}</coordinates></LineString></Placemark>")


def point_pm(name: str | None, pt) -> str:
    n = f"<name>{name}</name>" if name is not None else ""
    return f"<Placemark>{n}<Point><coordinates>{coords_text([pt])}</coordinates></Point></Placemark>"


def kml_doc(body: str, ns: str | None = KML22) -> str:
    xmlns = f' xmlns="{ns}"' if ns else ""
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<kml{xmlns}><Document>{body}</Document></kml>\n'


def write(tmp_path: Path, name: str, text: str | bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return p


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def offset(lon: float, lat: float, east_m: float, north_m: float) -> tuple[float, float]:
    lon2, lat2, _ = GEOD.fwd(lon, lat, 90.0, east_m) if east_m else (lon, lat, 0)
    lon3, lat3, _ = GEOD.fwd(lon2, lat2, 0.0, north_m) if north_m else (lon2, lat2, 0)
    return float(lon3), float(lat3)


def rect(lon: float, lat: float, w_m: float, h_m: float):
    """Rectangle ring (open) with south-west corner at (lon, lat)."""
    return [offset(lon, lat, 0, 0), offset(lon, lat, w_m, 0),
            offset(lon, lat, w_m, h_m), offset(lon, lat, 0, h_m)]


# ---------------------------------------------------------------------------
# synthetic DEM fetchers
# ---------------------------------------------------------------------------
def _grid(bbox, spacing_deg: float):
    min_lon, min_lat, max_lon, max_lat = bbox
    lons = np.arange(min_lon, max_lon + spacing_deg, spacing_deg)
    lats = np.arange(min_lat, max_lat + spacing_deg, spacing_deg)
    lon_c, lat_c = float(lons.mean()), float(lats.mean())
    # Same metric scale the analysis uses (geodesic cell size at the grid centre).
    m_per_deg_x = GEOD.inv(lon_c - spacing_deg / 2, lat_c, lon_c + spacing_deg / 2, lat_c)[2] / spacing_deg
    m_per_deg_y = GEOD.inv(lon_c, lat_c - spacing_deg / 2, lon_c, lat_c + spacing_deg / 2)[2] / spacing_deg
    LON, LAT = np.meshgrid(lons, lats)
    return lons, lats, LON, LAT, (LON - lon_c) * m_per_deg_x, (LAT - lat_c) * m_per_deg_y


def function_fetcher(fn, spacing_deg: float = 1 / 3600, calls: list | None = None):
    """Fetcher whose elevation is fn(LON, LAT, x_m, y_m) (x/y metres from the grid centre)."""
    def fetch(bbox, settings):
        if calls is not None:
            calls.append(bbox)
        lons, lats, LON, LAT, X, Y = _grid(bbox, spacing_deg)
        z = np.asarray(fn(LON, LAT, X, Y), dtype=float) * np.ones_like(LON)
        return DemGrid(lons=lons, lats=lats, z=z, info=dict(SYNTH_INFO))
    return fetch


def plane_fetcher(slope_deg: float, base: float = 50.0, direction: str = "east", **kw):
    """Plane rising toward `direction` ("east" or "north") at slope_deg."""
    t = math.tan(math.radians(slope_deg))
    if direction == "east":
        return function_fetcher(lambda LON, LAT, X, Y: base + t * X, **kw)
    return function_fetcher(lambda LON, LAT, X, Y: base + t * Y, **kw)
