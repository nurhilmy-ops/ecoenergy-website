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


# ---------------------------------------------------------------------------
# result dicts for flag unit tests (no DEM, no geometry)
# ---------------------------------------------------------------------------
FLAT_BINS = {"0-2": 100.0, "2-5": 0.0, "5-10": 0.0, "10-15": 0.0, "15-25": 0.0,
             "25-35": 0.0, ">35": 0.0}


def site_result(name: str = "Lot 1", *, bins: dict | None = None, elev_min: float = 10.0,
                elev_max: float = 20.0, area_ha: float = 30.0, relief: float | None = None,
                grades: dict | None = None, cells: int = 400) -> dict:
    """A result.json site entry; KPKT shares are summed from the slope bins."""
    b = dict(FLAT_BINS if bins is None else bins)
    site = {
        "name": name, "area_ha": area_ha, "elev_min_m": elev_min, "elev_max_m": elev_max,
        "relief_m": elev_max - elev_min if relief is None else relief,
        "slope_p90_deg": 1.0, "cells": cells, "slope_bins_pct": b,
        "kpkt_pct": {"I": b["0-2"] + b["2-5"] + b["5-10"] + b["10-15"], "II": b["15-25"],
                     "III": b["25-35"], "IV": b[">35"]},
    }
    if grades is not None:
        site["steeper_than_grade_pct"] = grades
    return site


def result_with(sites: list[dict], *, state: str | None = "Selangor", scheme: str | None = "lss",
                routes: list[dict] | None = None, provider: str = "copernicus") -> dict:
    """A minimal result dict that flags.build_flags / build_followups / build_caveats accept."""
    return {
        "meta": {"scheme": scheme},
        "dem": {"provider": provider, "name": "Copernicus DEM GLO-30",
                "model_type": "DSM (surface model: includes tree canopy and buildings)",
                "epoch": "December 2010 – January 2015 (TanDEM-X acquisitions)",
                "vertical_datum": "EGM2008", "nominal_resolution_m": 30, "grid_spacing_m": 30.7,
                "nodata_pct": 0.0, "sends_coordinates_to_third_party": provider == "opentopodata"},
        "location": {"state": state, "district": None, "utm_epsg": "EPSG:32647"},
        "totals": {"total_area_ha": round(sum(s["area_ha"] for s in sites), 2)},
        "sites": sites, "routes": routes or [], "contour_interval_m": 5.0,
        "kpkt_overall_pct": {"I": 100.0, "II": 0.0, "III": 0.0, "IV": 0.0},
    }


def route_result(name: str = "Access", max_grade_pct: float = 5.0) -> dict:
    return {"name": name, "length_km": 1.0, "elev_min_m": 10.0, "elev_max_m": 50.0,
            "total_ascent_m": 40.0, "max_grade_pct": max_grade_pct}
