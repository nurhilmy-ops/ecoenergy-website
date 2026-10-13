"""Terrain analysis on a DEM grid: slope, per-site statistics, KPKT split, routes, profiles.

All statistics for a site are computed from DEM cells whose centres fall inside the
polygon (exterior ring minus holes); the buffer around the sites is only context for
the maps and for the slope gradient at the site edges.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field

import numpy as np
import shapely
from pyproj import Geod
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import distance_transform_edt
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

from ..config import Settings
from .dem import NO_COVERAGE_MESSAGE, DemGrid
from .kml import Feature, ScreeningError, SiteInput, feature_geometry

GEOD = Geod(ellps="WGS84")

# KPKT hill-land slope classes (degrees): I < 15, II 15–25, III 25–35, IV >= 35.
KPKT_CLASSES = ("I", "II", "III", "IV")
KPKT_EDGES_DEG = (0.0, 15.0, 25.0, 35.0, math.inf)
# Finer bins for the slope map and tables (percent of site cells).
SLOPE_BINS = (("0-2", 0.0, 2.0), ("2-5", 2.0, 5.0), ("5-10", 5.0, 10.0),
              ("10-15", 10.0, 15.0), ("15-25", 15.0, 25.0), ("25-35", 25.0, 35.0),
              (">35", 35.0, math.inf))

# Analysis frame = features bbox + max(150 m, 10% of extent): enough context for the
# maps and keeps the slope at site edges free of grid-edge effects.
MIN_BUFFER_M = 150.0
BUFFER_FRACTION = 0.10
# A 3x3 block is the smallest footprint with a meaningful slope distribution; below it
# the site is sampled bilinearly instead (and flagged as small_site).
SMALL_SITE_MIN_CELLS = 9
SMALL_SITE_SAMPLES = 200
# >= this share of NaN cells means the frame is essentially off the DEM (e.g. offshore).
NO_COVERAGE_PCT = 95.0
# Route grades are measured over at least this horizontal distance (~3 DEM cells) so
# single-cell noise does not masquerade as a steep pitch.
GRADE_WINDOW_M = 90.0


@dataclass
class SiteStats:
    name: str
    polygon: Polygon
    area_ha: float
    perimeter_m: float
    centroid: tuple[float, float]
    cells: int
    small: bool
    elev_min: float
    elev_max: float
    elev_mean: float
    slope_mean: float
    slope_p90: float
    slope_max: float
    kpkt_pct: dict[str, float]
    bins_pct: dict[str, float]

    @property
    def relief(self) -> float:
        return self.elev_max - self.elev_min


@dataclass
class RouteStats:
    name: str
    coords: list[tuple[float, float]]
    lons: np.ndarray          # sample positions every ~grid spacing (vertices kept)
    lats: np.ndarray
    dist_m: np.ndarray        # cumulative distance of each sample
    elev: np.ndarray          # bilinear DEM elevation at each sample (NaN = no data)
    length_m: float
    elev_min: float
    elev_max: float
    ascent_m: float
    max_grade_pct: float


@dataclass
class PointStats:
    name: str
    lon: float
    lat: float
    elev: float


@dataclass
class Transect:
    direction: str            # "W-E" | "S-N"
    through: str              # name of the site (or "features") it passes through
    dist_m: np.ndarray
    elev: np.ndarray
    inside: np.ndarray        # bool: sample inside any site polygon


@dataclass
class Analysis:
    site: SiteInput
    dem: DemGrid
    z_filled: np.ndarray      # z with NaN replaced by the nearest valid value (display only)
    slope: np.ndarray         # degrees, NaN where z is NaN
    dx_m: float
    dy_m: float
    nodata_pct: float
    centroid: tuple[float, float]
    utm_epsg: str
    sites: list[SiteStats]
    routes: list[RouteStats]
    points: list[PointStats]
    transects: list[Transect]
    site_mask: np.ndarray     # bool [lat, lon]: cell centre inside any site polygon
    contour_interval_m: float
    kpkt_overall: dict[str, float | None]
    bins_overall: dict[str, float | None] = field(default_factory=dict)

    @property
    def grid_spacing_m(self) -> float:
        return (self.dx_m + self.dy_m) / 2

    @property
    def cells(self) -> int:
        return int(self.dem.z.size)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def analysis_bbox(site: SiteInput) -> tuple[float, float, float, float]:
    """Features bbox + buffer of max(150 m, 10% of the extent)."""
    min_lon, min_lat, max_lon, max_lat = site.bbox
    buf = max(MIN_BUFFER_M, BUFFER_FRACTION * site.extent_km * 1000.0)
    lat_c = (min_lat + max_lat) / 2
    lon_c = (min_lon + max_lon) / 2
    e_lon, _, _ = GEOD.fwd(lon_c, lat_c, 90.0, buf)
    _, n_lat, _ = GEOD.fwd(lon_c, lat_c, 0.0, buf)
    dlon, dlat = abs(e_lon - lon_c), abs(n_lat - lat_c)
    return (min_lon - dlon, min_lat - dlat, max_lon + dlon, max_lat + dlat)


def utm_epsg(lon: float, lat: float) -> str:
    zone = int((lon + 180.0) // 6.0) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def nice_interval(x: float) -> float:
    """Nearest 1/2/5 x 10^n to x."""
    if not (x > 0 and math.isfinite(x)):
        return 1.0
    exp = math.floor(math.log10(x))
    f = x / 10 ** exp
    nf = 1 if f < 1.5 else 2 if f < 3.5 else 5 if f < 7.5 else 10
    return float(nf * 10 ** exp)


def contour_interval(relief_m: float, settings: Settings) -> float:
    return max(float(settings.contour_min_interval_m), nice_interval(relief_m / 10.0))


def _nanstats(values: np.ndarray) -> tuple[float, float, float]:
    v = values[np.isfinite(values)]
    if v.size == 0:
        return math.nan, math.nan, math.nan
    return float(v.min()), float(v.max()), float(v.mean())


def _class_pct(slopes: np.ndarray, edges) -> list[float]:
    s = slopes[np.isfinite(slopes)]
    if s.size == 0:
        return [math.nan] * (len(edges) - 1)
    return [100.0 * float(np.count_nonzero((s >= lo) & (s < hi))) / s.size
            for lo, hi in zip(edges[:-1], edges[1:])]


def _fill_nearest(z: np.ndarray) -> np.ndarray:
    nan = np.isnan(z)
    if not nan.any():
        return z.copy()
    idx = distance_transform_edt(nan, return_distances=False, return_indices=True)
    return z[tuple(idx)]


def _spacing_m(dem: DemGrid) -> tuple[float, float]:
    """Metric cell size at the grid centre (geodesic)."""
    lons, lats = dem.lons, dem.lats
    lon_c, lat_c = float(lons.mean()), float(lats.mean())
    dlon = float(np.diff(lons).mean())
    dlat = float(np.diff(lats).mean())
    dx = GEOD.inv(lon_c - dlon / 2, lat_c, lon_c + dlon / 2, lat_c)[2]
    dy = GEOD.inv(lon_c, lat_c - dlat / 2, lon_c, lat_c + dlat / 2)[2]
    return dx, dy


def _polygon_mask(poly: Polygon, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Bool [lat, lon] mask of cell centres inside poly (holes excluded). Only the
    polygon's bounding window is tested."""
    mask = np.zeros((lats.size, lons.size), dtype=bool)
    minx, miny, maxx, maxy = poly.bounds
    xs = np.searchsorted(lons, [minx, maxx])
    ys = np.searchsorted(lats, [miny, maxy])
    x0, x1 = int(xs[0]), int(min(xs[1] + 1, lons.size))
    y0, y1 = int(ys[0]), int(min(ys[1] + 1, lats.size))
    if x1 <= x0 or y1 <= y0:
        return mask
    gx, gy = np.meshgrid(lons[x0:x1], lats[y0:y1])
    shapely.prepare(poly)
    mask[y0:y1, x0:x1] = shapely.contains_xy(poly, gx, gy)
    return mask


def _dense_points(poly: Polygon, target: int = SMALL_SITE_SAMPLES) -> tuple[np.ndarray, np.ndarray]:
    """A regular point set inside a (small) polygon, refined until it has enough points."""
    minx, miny, maxx, maxy = poly.bounds
    n = max(4, int(math.sqrt(target)))
    for _ in range(6):
        gx, gy = np.meshgrid(np.linspace(minx, maxx, n), np.linspace(miny, maxy, n))
        inside = shapely.contains_xy(poly, gx, gy)
        if inside.sum() >= target // 4:
            return gx[inside], gy[inside]
        n *= 2
    rp = poly.representative_point()
    return np.array([rp.x]), np.array([rp.y])


def _interp(dem: DemGrid, values: np.ndarray) -> RegularGridInterpolator:
    return RegularGridInterpolator((dem.lats, dem.lons), values, method="linear",
                                   bounds_error=False, fill_value=np.nan)


# ---------------------------------------------------------------------------
# per-feature analysis
# ---------------------------------------------------------------------------
def _site_stats(f: Feature, dem: DemGrid, slope: np.ndarray, slope_filled: np.ndarray,
                ) -> tuple[SiteStats, np.ndarray]:
    poly = Polygon(f.coords, f.holes)
    area, perim = GEOD.geometry_area_perimeter(orient(poly, 1.0))
    c = poly.centroid
    mask = _polygon_mask(poly, dem.lons, dem.lats)
    cells = int(mask.sum())
    if cells >= SMALL_SITE_MIN_CELLS:
        elev = dem.z[mask]
        slopes = slope[mask]
    else:
        # Too few cell centres inside: sample bilinearly on a dense point set instead.
        px, py = _dense_points(poly)
        pts = np.column_stack([py, px])
        elev = _interp(dem, dem.z)(pts)
        slopes = _interp(dem, slope_filled)(pts)
        slopes[~np.isfinite(elev)] = np.nan
    emin, emax, emean = _nanstats(elev)
    s = slopes[np.isfinite(slopes)]
    smean = float(s.mean()) if s.size else math.nan
    sp90 = float(np.percentile(s, 90)) if s.size else math.nan
    smax = float(s.max()) if s.size else math.nan
    kpkt = dict(zip(KPKT_CLASSES, _class_pct(slopes, KPKT_EDGES_DEG)))
    bin_edges = [b[1] for b in SLOPE_BINS] + [math.inf]
    bins = dict(zip([b[0] for b in SLOPE_BINS], _class_pct(slopes, bin_edges)))
    stats = SiteStats(
        name=f.name, polygon=poly, area_ha=abs(area) / 1e4, perimeter_m=abs(perim),
        centroid=(c.x, c.y), cells=cells, small=cells < SMALL_SITE_MIN_CELLS,
        elev_min=emin, elev_max=emax, elev_mean=emean,
        slope_mean=smean, slope_p90=sp90, slope_max=smax, kpkt_pct=kpkt, bins_pct=bins)
    return stats, mask


def _sample_line(coords: list[tuple[float, float]], step_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Points every ~step_m along a lon/lat polyline (vertices kept)."""
    lons, lats = [coords[0][0]], [coords[0][1]]
    for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
        seg = GEOD.inv(x0, y0, x1, y1)[2]
        n = max(1, math.ceil(seg / step_m))
        t = np.arange(1, n + 1) / n
        lons.extend(x0 + (x1 - x0) * t)
        lats.extend(y0 + (y1 - y0) * t)
    return np.asarray(lons), np.asarray(lats)


def _smooth3(z: np.ndarray) -> np.ndarray:
    out = z.copy()
    if z.size >= 3:
        out[1:-1] = (z[:-2] + z[1:-1] + z[2:]) / 3.0
    return out


def max_grade_pct(dist_m: np.ndarray, elev: np.ndarray, window_m: float = GRADE_WINDOW_M) -> float:
    """Steepest |rise|/run (%) over horizontal windows of at least window_m."""
    ok = np.isfinite(elev)
    d, z = dist_m[ok], elev[ok]
    if d.size < 2 or d[-1] - d[0] <= 0:
        return math.nan
    j = np.searchsorted(d, d + window_m, side="left")
    valid = j < d.size
    if not valid.any():   # route shorter than one window: use its end-to-end grade
        return 100.0 * abs(z[-1] - z[0]) / (d[-1] - d[0])
    i = np.nonzero(valid)[0]
    j = j[valid]
    return float(np.max(100.0 * np.abs(z[j] - z[i]) / (d[j] - d[i])))


def total_ascent_m(elev: np.ndarray) -> float:
    z = elev[np.isfinite(elev)]
    if z.size < 2:
        return math.nan
    return float(np.clip(np.diff(_smooth3(z)), 0, None).sum())


def _route_stats(f: Feature, dem: DemGrid, step_m: float) -> RouteStats:
    lons, lats = _sample_line(f.coords, step_m)
    seg = GEOD.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])[2] if lons.size > 1 else np.array([])
    dist = np.concatenate([[0.0], np.cumsum(seg)])
    elev = _interp(dem, dem.z)(np.column_stack([lats, lons]))
    emin, emax, _ = _nanstats(elev)
    return RouteStats(
        name=f.name, coords=f.coords, lons=lons, lats=lats, dist_m=dist, elev=elev,
        length_m=float(GEOD.geometry_length(LineString(f.coords))),
        elev_min=emin, elev_max=emax, ascent_m=total_ascent_m(elev),
        max_grade_pct=max_grade_pct(dist, elev))


def _transects(dem: DemGrid, sites: list[SiteStats], fallback: tuple[float, float],
               union, dx: float, dy: float) -> list[Transect]:
    if sites:
        big = max(sites, key=lambda s: s.area_ha)
        c = big.polygon.centroid
        if not big.polygon.contains(c):          # concave site: centroid may fall outside it
            c = big.polygon.representative_point()
        lon_c, lat_c, through = c.x, c.y, big.name
    else:
        (lon_c, lat_c), through = fallback, ""
    interp = _interp(dem, dem.z)
    out = []
    for direction in ("W-E", "S-N"):
        if direction == "W-E":
            lons, lats = dem.lons, np.full(dem.lons.size, lat_c)
            dist = (dem.lons - dem.lons[0]) / np.diff(dem.lons).mean() * dx
        else:
            lons, lats = np.full(dem.lats.size, lon_c), dem.lats
            dist = (dem.lats - dem.lats[0]) / np.diff(dem.lats).mean() * dy
        elev = interp(np.column_stack([lats, lons]))
        inside = (shapely.contains_xy(union, lons, lats) if union is not None
                  else np.zeros(lons.size, dtype=bool))
        out.append(Transect(direction=direction, through=through, dist_m=dist,
                            elev=elev, inside=np.asarray(inside, dtype=bool)))
    return out


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------
def analyse(site: SiteInput, dem: DemGrid, settings: Settings) -> Analysis:
    dem.validate()
    # Own copies: NaN normalisation below must not mutate the fetcher's arrays.
    dem = DemGrid(lons=np.array(dem.lons, dtype=np.float64), lats=np.array(dem.lats, dtype=np.float64),
                  z=np.array(dem.z, dtype=np.float64), info=dict(dem.info))
    nan = ~np.isfinite(dem.z)
    dem.z[nan] = np.nan
    nodata_pct = 100.0 * float(nan.mean())
    if nodata_pct >= NO_COVERAGE_PCT:
        raise ScreeningError(NO_COVERAGE_MESSAGE, "no_dem_coverage")

    dx, dy = _spacing_m(dem)
    # Gradient on a temporarily gap-filled grid, then gaps are masked back out.
    z_filled = _fill_nearest(dem.z)
    gy, gx = np.gradient(z_filled, dy, dx)
    slope_filled = np.degrees(np.arctan(np.hypot(gx, gy)))
    slope = slope_filled.copy()
    slope[nan] = np.nan

    sites: list[SiteStats] = []
    site_mask = np.zeros(dem.z.shape, dtype=bool)
    for f in site.features:
        if f.kind == "polygon":
            stats, mask = _site_stats(f, dem, slope, slope_filled)
            sites.append(stats)
            site_mask |= mask
    step = min(dx, dy)
    routes = [_route_stats(f, dem, step) for f in site.features if f.kind == "line"]
    pinterp = _interp(dem, dem.z)
    points = [PointStats(name=f.name, lon=f.coords[0][0], lat=f.coords[0][1],
                         elev=float(pinterp([[f.coords[0][1], f.coords[0][0]]])[0]))
              for f in site.features if f.kind == "point"]

    if sites:
        union = shapely.union_all([s.polygon for s in sites])
        cen = union.centroid
    else:
        union = None
        cen = shapely.GeometryCollection([feature_geometry(f) for f in site.features]).centroid
    centroid = (float(cen.x), float(cen.y))

    # Area-weighted overall split; sites without valid cells do not contribute.
    def overall(key: str, labels) -> dict[str, float | None]:
        rows = [(s.area_ha, getattr(s, key)) for s in sites
                if all(math.isfinite(v) for v in getattr(s, key).values())]
        total = sum(a for a, _ in rows)
        if not rows or total <= 0:
            return {k: None for k in labels}
        return {k: sum(a * d[k] for a, d in rows) / total for k in labels}

    finite = dem.z[np.isfinite(dem.z)]
    relief = float(finite.max() - finite.min()) if finite.size else 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        transects = _transects(dem, sites, centroid, union, dx, dy)
    return Analysis(
        site=site, dem=dem, z_filled=z_filled, slope=slope, dx_m=dx, dy_m=dy,
        nodata_pct=nodata_pct, centroid=centroid, utm_epsg=utm_epsg(*centroid),
        sites=sites, routes=routes, points=points, transects=transects,
        site_mask=site_mask, contour_interval_m=contour_interval(relief, settings),
        kpkt_overall=overall("kpkt_pct", KPKT_CLASSES),
        bins_overall=overall("bins_pct", [b[0] for b in SLOPE_BINS]))


# ---------------------------------------------------------------------------
# result.json sections
# ---------------------------------------------------------------------------
def num(x, ndigits: int):
    """Round to ndigits; NaN/inf/None -> None (JSON null)."""
    if x is None:
        return None
    x = float(x)
    return round(x, ndigits) if math.isfinite(x) else None


def _pct_dict(d: dict) -> dict:
    return {k: num(v, 1) for k, v in d.items()}


def result_sections(an: Analysis) -> dict:
    """The numeric parts of result.json (schema_version 1), rounded, NaN -> null."""
    info = an.dem.info
    return {
        "dem": {
            "provider": info["provider"],
            "name": info["name"],
            "model_type": info["model_type"],
            "epoch": info["epoch"],
            "vertical_datum": info["vertical_datum"],
            "nominal_resolution_m": info["nominal_resolution_m"],
            "grid_spacing_m": num(an.grid_spacing_m, 1),
            "cells_analysed": an.cells,
            "nodata_pct": num(an.nodata_pct, 1),
            "attribution": info["attribution"],
        },
        "location": {
            "centroid_lon": num(an.centroid[0], 6),
            "centroid_lat": num(an.centroid[1], 6),
            "state": None,
            "district": None,
            "utm_epsg": an.utm_epsg,
            "boundary_attribution": "",
        },
        "totals": {
            "polygon_count": len(an.sites),
            "line_count": len(an.routes),
            "point_count": len(an.points),
            "total_area_ha": num(sum(s.area_ha for s in an.sites), 2),
            "total_line_km": num(sum(r.length_m for r in an.routes) / 1000.0, 2),
        },
        "sites": [{
            "name": s.name,
            "area_ha": num(s.area_ha, 2),
            "perimeter_m": num(s.perimeter_m, 1),
            "centroid": [num(s.centroid[0], 6), num(s.centroid[1], 6)],
            "elev_min_m": num(s.elev_min, 1),
            "elev_max_m": num(s.elev_max, 1),
            "elev_mean_m": num(s.elev_mean, 1),
            "relief_m": num(s.relief, 1),
            "slope_mean_deg": num(s.slope_mean, 1),
            "slope_p90_deg": num(s.slope_p90, 1),
            "slope_max_deg": num(s.slope_max, 1),
            "kpkt_pct": _pct_dict(s.kpkt_pct),
            "slope_bins_pct": _pct_dict(s.bins_pct),
            "cells": s.cells,
        } for s in an.sites],
        "kpkt_overall_pct": _pct_dict(an.kpkt_overall),
        "routes": [{
            "name": r.name,
            "length_km": num(r.length_m / 1000.0, 2),
            "elev_min_m": num(r.elev_min, 1),
            "elev_max_m": num(r.elev_max, 1),
            "total_ascent_m": num(r.ascent_m, 1),
            "max_grade_pct": num(r.max_grade_pct, 1),
        } for r in an.routes],
        "points": [{
            "name": p.name,
            "lon": num(p.lon, 6),
            "lat": num(p.lat, 6),
            "elev_m": num(p.elev, 1),
        } for p in an.points],
        "contour_interval_m": num(an.contour_interval_m, 1),
    }
