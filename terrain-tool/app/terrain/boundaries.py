"""State / district lookup from the bundled geoBoundaries (gbOpen) data for Malaysia.

Layers are loaded lazily on first use (thread-safe) and indexed with an STRtree.
A point is assigned to the polygon that contains it; points just offshore or in a
simplification gap fall back to the nearest polygon within 5 km.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import shapely
from pyproj import Geod
from shapely.geometry import Point, shape
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from ..config import APP_ROOT

log = logging.getLogger(__name__)

BOUNDARY_DIR = APP_ROOT / "data" / "boundaries"
ADM1_PATH = BOUNDARY_DIR / "geoBoundaries-MYS-ADM1_simplified.geojson"   # shapeName = state (ODbL 1.0, OSM)
ADM2_PATH = BOUNDARY_DIR / "geoBoundaries-MYS-ADM2_simplified.geojson"   # shapeName = district (CC BY 3.0)

BOUNDARY_ATTRIBUTION = (
    "Administrative boundaries: geoBoundaries (gbOpen) — states © OpenStreetMap contributors "
    "(ODbL 1.0); districts citypopulation.de (CC BY 3.0).")

NEAREST_MAX_M = 5000.0
# Planar pre-filter for the nearest search, in degrees (~5.5 km at the equator).
_NEAREST_SEARCH_DEG = 0.05

GEOD = Geod(ellps="WGS84")


class _Layer:
    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.names: list[str | None] = []
        geoms = []
        for feat in data.get("features", []):
            if not feat.get("geometry"):
                continue
            g = shape(feat["geometry"])
            if not g.is_valid:
                g = shapely.make_valid(g)
            geoms.append(g)
            name = (feat.get("properties") or {}).get("shapeName")
            self.names.append(str(name) if name else None)
        self.geoms = geoms
        self.tree = STRtree(geoms)

    def lookup(self, pt: Point) -> str | None:
        hits = self.tree.query(pt, predicate="intersects")
        if len(hits):
            return self.names[int(min(hits))]
        idx = self.tree.query_nearest(pt, max_distance=_NEAREST_SEARCH_DEG)
        best, best_d = None, NEAREST_MAX_M
        for i in idx:
            near = nearest_points(self.geoms[int(i)], pt)[0]
            d = GEOD.inv(pt.x, pt.y, near.x, near.y)[2]
            if d <= best_d:
                best, best_d = self.names[int(i)], d
        return best


_lock = threading.Lock()
_layers: tuple[_Layer, _Layer] | None = None


def _load() -> tuple[_Layer, _Layer]:
    global _layers
    with _lock:
        if _layers is None:
            _layers = (_Layer(ADM1_PATH), _Layer(ADM2_PATH))
        return _layers


def lookup(lon: float, lat: float) -> tuple[str | None, str | None]:
    """(state, district) for a WGS84 point, or None where no boundary is within 5 km."""
    try:
        states, districts = _load()
    except (OSError, ValueError) as exc:     # missing/corrupt bundled data: degrade, don't fail the job
        log.error("boundary data unavailable: %s", exc)
        return None, None
    pt = Point(lon, lat)
    return states.lookup(pt), districts.lookup(pt)
