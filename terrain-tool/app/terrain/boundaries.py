"""State / district lookup from the bundled DOSM district boundaries for Malaysia.

Source: Department of Statistics Malaysia (DOSM), github.com/dosm-malaysia/data-open,
datasets/geodata/administrative_2_district.geojson (160 districts, CRS84, properties
``state`` and ``district`` among others), used under the DOSM Open Data Licence, which
allows commercial use but forbids suggesting official status or endorsement. One file
gives both the state and the district. Names are kept exactly as DOSM spells them
(e.g. "Pulau Pinang", "Melaka", "W.P. Kuala Lumpur", "W.P. Putrajaya").

The layer is loaded lazily on first use (thread-safe) and indexed with an STRtree. A few
DOSM geometries are invalid (degenerate rings); they are repaired with shapely.make_valid
at load time and only their polygonal parts are kept. A point is assigned to the district
that contains it; points just offshore or in a simplification gap fall back to the
nearest district within 5 km.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import shapely
from pyproj import Geod
from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from ..config import APP_ROOT

log = logging.getLogger(__name__)

BOUNDARY_DIR = APP_ROOT / "data" / "boundaries"
DISTRICTS_PATH = BOUNDARY_DIR / "dosm_administrative_2_district.geojson"

# DOSM Open Data Licence: commercial use allowed; must not suggest official status or
# that DOSM endorses the user or the use.
BOUNDARY_ATTRIBUTION = (
    "State and district boundaries: Department of Statistics Malaysia (DOSM) open data "
    "(github.com/dosm-malaysia/data-open), used under the DOSM Open Data Licence. "
    "No endorsement by DOSM is implied.")

NEAREST_MAX_M = 5000.0
# Planar pre-filter for the nearest search, in degrees (~5.5 km at the equator).
_NEAREST_SEARCH_DEG = 0.05

GEOD = Geod(ellps="WGS84")


def _polygonal(geom):
    """The polygonal part of a geometry (make_valid can return a collection that also
    holds the lines/points left over from degenerate rings), or None if there is none."""
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom if not geom.is_empty else None
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    polys = [p for g in parts for p in (g.geoms if isinstance(g, MultiPolygon) else [g])]
    return MultiPolygon(polys) if polys else None


class _Districts:
    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.names: list[tuple[str | None, str | None]] = []
        geoms = []
        for feat in data.get("features", []):
            if not feat.get("geometry"):
                continue
            g = shape(feat["geometry"])
            if not g.is_valid:
                g = _polygonal(shapely.make_valid(g))
                if g is None:
                    continue
            props = feat.get("properties") or {}
            state, district = props.get("state"), props.get("district")
            geoms.append(g)
            self.names.append((str(state) if state else None, str(district) if district else None))
        if not geoms:
            raise ValueError(f"no district polygons in {path}")
        self.geoms = geoms
        self.tree = STRtree(geoms)

    def lookup(self, pt: Point) -> tuple[str | None, str | None]:
        hits = self.tree.query(pt, predicate="intersects")
        if len(hits):
            return self.names[int(min(hits))]
        idx = self.tree.query_nearest(pt, max_distance=_NEAREST_SEARCH_DEG)
        best, best_d = (None, None), NEAREST_MAX_M
        for i in idx:
            near = nearest_points(self.geoms[int(i)], pt)[0]
            d = GEOD.inv(pt.x, pt.y, near.x, near.y)[2]
            if d <= best_d:
                best, best_d = self.names[int(i)], d
        return best


_lock = threading.Lock()
_districts: _Districts | None = None


def _load() -> _Districts:
    global _districts
    with _lock:
        if _districts is None:
            _districts = _Districts(DISTRICTS_PATH)
        return _districts


def lookup(lon: float, lat: float) -> tuple[str | None, str | None]:
    """(state, district) for a WGS84 point, as DOSM spells them, or (None, None) where no
    district is within 5 km."""
    try:
        districts = _load()
    except (OSError, ValueError) as exc:     # missing/corrupt bundled data: degrade, don't fail the job
        log.error("boundary data unavailable: %s", exc)
        return None, None
    return districts.lookup(Point(lon, lat))
