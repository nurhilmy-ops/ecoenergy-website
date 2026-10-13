"""DEM providers. Each returns a DemGrid on a regular lon/lat grid covering a bbox.

Providers (``settings.dem_provider``):

* ``copernicus`` (default) - Copernicus DEM GLO-30 Cloud-Optimised GeoTIFFs read
  over HTTPS with windowed reads (only the blocks covering the bbox are fetched). The
  AWS tiles carry no nodata value and store sea as exactly 0 m; those cells become NaN.
* ``opentopodata`` - the public OpenTopoData API (SRTM 1"), for environments
  without rasterio. Small grid (<= 1000 points) because of the public API limits.
* ``geotiff`` - a local GeoTIFF/VRT in EPSG:4326 at ``settings.dem_geotiff_path``.

Elevations are never fabricated: transport failures raise ScreeningError
``dem_unavailable``; cells without data are NaN.
"""
from __future__ import annotations

import logging
import math
import time
import warnings
from dataclasses import dataclass
from typing import Callable

import numpy as np
from pyproj import Geod

from ..config import Settings
from .kml import ScreeningError

log = logging.getLogger(__name__)

Bbox = tuple[float, float, float, float]          # (min_lon, min_lat, max_lon, max_lat)
GEOD = Geod(ellps="WGS84")

DEM_UNAVAILABLE_MESSAGE = (
    "The elevation data service could not be reached, so the terrain screening could not "
    "be completed. Please try again later.")
NO_COVERAGE_MESSAGE = (
    "The elevation model has no data for this location. Please check that the site is on "
    "land in Malaysia (it may be offshore).")

# --- Copernicus DEM GLO-30 (strings kept here so they can be corrected in one place) ---
COPERNICUS_NAME = "Copernicus DEM GLO-30"
COPERNICUS_MODEL_TYPE = "DSM (surface model: includes tree canopy and buildings)"
# Copernicus DEM Product Handbook (GEO1988-CopernicusDEM-SPE-002, issue 5.0) s.2.1: the
# TanDEM-X / WorldDEM source data were acquired between December 2010 and January 2015.
COPERNICUS_EPOCH = "December 2010 – January 2015 (TanDEM-X acquisitions)"
COPERNICUS_VERTICAL_DATUM = "EGM2008"
COPERNICUS_NOMINAL_RES_M = 30
# Licence for the use of the Copernicus WorldDEM-30 (COP-DEM-GLO-30-F), Art. 6(b): the
# notice required where the data have been adapted or modified (our slopes, maps and
# contours are adaptations). Kept verbatim.
COPERNICUS_ATTRIBUTION = (
    "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and "
    "Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all "
    "rights reserved.")
# Same licence, Art. 6(c): sentence that must appear in a licence or legal notice when the
# data (modified or not) are communicated to the public. Kept verbatim.
COPERNICUS_DISCLAIMER = (
    "The organisations in charge of the Copernicus programme by law or by delegation do not "
    "incur any liability for any use of the Copernicus WorldDEM-30.")
# Short credit for the figure footers (the full Art. 6(b) notice is in every report).
COPERNICUS_STAMP_CREDIT = (
    "Copernicus WorldDEM-30 © DLR/Airbus, provided under COPERNICUS by EU & ESA")
# Posts per degree (1 arc-second). Holds for tiles between 50°S and 50°N, i.e. all of Malaysia.
COPERNICUS_POSTS_PER_DEG = 3600
COPERNICUS_GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",     # don't list the bucket for sidecar files
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
    # Jobs run one at a time, so a stalled endpoint must fail fast: give up on a connection
    # after 10 s, on a transfer that moves no data for 15 s, and on any request after 60 s;
    # one retry. A blackholed bucket then fails a job in about 30 s, not 3 minutes.
    GDAL_HTTP_CONNECTTIMEOUT=10,
    GDAL_HTTP_LOW_SPEED_TIME=15,
    GDAL_HTTP_LOW_SPEED_LIMIT=1,
    GDAL_HTTP_TIMEOUT=60,
    GDAL_HTTP_MAX_RETRY=1,
    GDAL_HTTP_RETRY_DELAY=1,
)
# Copernicus GLO-30 on AWS: "ocean areas ... assume height values equal to zero" and the
# COGs declare no nodata value, so sea pixels are exactly 0.0 m (land at or below sea level
# is stored negative or positive, not 0.0). They are treated as no data.
COPERNICUS_SEA_VALUE = 0.0

# --- SRTM via OpenTopoData ---
SRTM_NAME = "SRTM 1 arc-second (via OpenTopoData)"
SRTM_MODEL_TYPE = "DSM-like radar surface model (C-band: partly includes tree canopy and buildings)"
# USGS EROS: SRTM flew on Space Shuttle Endeavour (STS-99), 11-22 February 2000.
SRTM_EPOCH = "11–22 February 2000"
# SRTM v3 User Guide (LP DAAC): heights in metres referenced to the WGS84/EGM96 geoid.
SRTM_VERTICAL_DATUM = "EGM96"
SRTM_NOMINAL_RES_M = 30
SRTM_ATTRIBUTION = ("SRTM 1 arc-second Global elevation data courtesy of NASA/USGS; "
                    "served by OpenTopoData (opentopodata.org).")
# Public API limits: 100 locations per request, 1 call per second, 1000 calls per day.
OTD_MAX_POINTS = 1000
OTD_BATCH = 100
OTD_CALL_INTERVAL_S = 1.05
OTD_RETRY_WAIT_S = 5.0
OTD_TIMEOUT_S = 30

# --- local GeoTIFF (override any of these via settings.extra["dem_geotiff_info"]) ---
GEOTIFF_NAME = "Local elevation model (GeoTIFF)"
GEOTIFF_MODEL_TYPE = "As supplied (check the source metadata for DSM/DTM)"
GEOTIFF_EPOCH = "unknown"
GEOTIFF_VERTICAL_DATUM = "unknown"
GEOTIFF_ATTRIBUTION = "Elevation data supplied by the operator."

# Whether exact site coordinates leave the server to reach the DEM. OpenTopoData is sent
# the analysis grid points (site coordinates) over HTTPS. The Copernicus provider only
# requests 1°×1° tile files / byte ranges by tile name from AWS S3, and the geotiff
# provider reads a local file, so neither discloses the site itself.
SENDS_COORDINATES = {"copernicus": False, "opentopodata": True, "geotiff": False}


@dataclass
class DemGrid:
    lons: np.ndarray          # 1-D, ascending, cell centres (degrees)
    lats: np.ndarray          # 1-D, ascending, cell centres (degrees)
    z: np.ndarray             # 2-D float64 [lat, lon]; NaN = no data
    info: dict                # provider, name, model_type, epoch, vertical_datum,
                              # nominal_resolution_m, attribution; optional: disclaimer
                              # (str|None), sends_coordinates_to_third_party (bool)

    def validate(self) -> None:
        """Raise ValueError if the grid is not a regular ascending lon/lat grid."""
        lons, lats, z = np.asarray(self.lons), np.asarray(self.lats), np.asarray(self.z)
        if lons.ndim != 1 or lats.ndim != 1 or z.shape != (lats.size, lons.size):
            raise ValueError(f"DemGrid shape mismatch: z{z.shape}, lats{lats.shape}, lons{lons.shape}")
        if lons.size < 3 or lats.size < 3:
            raise ValueError("DemGrid needs at least 3x3 cells")
        for axis in (lons, lats):
            d = np.diff(axis)
            if not (d > 0).all() or not np.allclose(d, d.mean(), rtol=1e-3, atol=0):
                raise ValueError("DemGrid axes must be regular and ascending")
        missing = {"provider", "name", "model_type", "epoch", "vertical_datum",
                   "nominal_resolution_m", "attribution"} - set(self.info)
        if missing:
            raise ValueError(f"DemGrid.info missing {sorted(missing)}")


DemFetcher = Callable[[Bbox, Settings], DemGrid]


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------
def decimation_factor(ny: int, nx: int, max_cells: int) -> int:
    """Smallest integer block size k that brings an ny x nx grid within max_cells (1 = fits)."""
    if ny * nx <= max_cells:
        return 1
    k = max(2, math.ceil(math.sqrt(ny * nx / max_cells)))
    while (ny // k) * (nx // k) > max_cells:
        k += 1
    return k


def decimate(lons: np.ndarray, lats: np.ndarray, z: np.ndarray, max_cells: int):
    """Block-average (nanmean) by an integer factor until the grid fits max_cells.

    The few rows/columns that do not fill a whole block are trimmed (split between both
    edges) so the result stays a regular grid; the analysis bbox carries a buffer of
    >= 150 m, far wider than one block.
    """
    ny, nx = z.shape
    k = decimation_factor(ny, nx, max_cells)
    if k == 1:
        return lons, lats, z
    ry, rx = ny % k, nx % k
    ys = slice(ry // 2, ny - (ry - ry // 2))
    xs = slice(rx // 2, nx - (rx - rx // 2))
    zc, lonc, latc = z[ys, xs], lons[xs], lats[ys]
    by, bx = zc.shape[0] // k, zc.shape[1] // k
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)   # all-NaN blocks stay NaN
        zb = np.nanmean(zc.reshape(by, k, bx, k), axis=(1, 3))
    return lonc.reshape(bx, k).mean(axis=1), latc.reshape(by, k).mean(axis=1), zb


def _import_rasterio():
    try:
        import rasterio  # noqa: F401  (imported lazily: optional for the opentopodata provider)
        from rasterio.windows import Window  # noqa: F401
    except ImportError as exc:
        # Name the real cause: an installed rasterio whose bundled GDAL misses a system library
        # (e.g. "libexpat.so.1: cannot open shared object file") fails here too.
        raise RuntimeError("rasterio could not be imported, so the copernicus and geotiff DEM providers "
                           f"cannot run ({exc}); install it (and any missing system library) or set "
                           "DEM_PROVIDER=opentopodata") from exc
    import rasterio
    return rasterio


def _unavailable(reason: str, exc: BaseException | None = None) -> ScreeningError:
    log.warning("DEM unavailable: %s (%s)", reason, exc)
    return ScreeningError(DEM_UNAVAILABLE_MESSAGE, "dem_unavailable")


# ---------------------------------------------------------------------------
# copernicus
# ---------------------------------------------------------------------------
def copernicus_tile_name(lat_floor: int, lon_floor: int) -> str:
    """Tile name from its south-west corner, e.g. (3, 101) -> Copernicus_DSM_COG_10_N03_00_E101_00_DEM."""
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat_floor):02d}_00_{ew}{abs(lon_floor):03d}_00_DEM"


def _is_missing(exc: BaseException, url: str) -> bool:
    """All-ocean tiles are simply not published: S3 answers 404 (local paths: no such file).
    Over HTTP only a 404 counts: GDAL words other failures (e.g. a timeout) as "does not exist
    in the file system", and those must report the service as unreachable, never as sea."""
    msg = str(exc).lower()
    if url.startswith(("http://", "https://")):
        return "404" in msg
    return "404" in msg or "no such file" in msg or "does not exist" in msg


def _place_tile(src, z: np.ndarray, i0: int, j0: int, n: int) -> None:
    """Copy the part of an open tile that overlaps the global post-index window into z.

    Global indices: lon = i / n, lat = j / n (cell centres, pixel-is-point). z rows run
    south -> north starting at j0, columns west -> east starting at i0.
    """
    from rasterio.windows import Window

    t = src.transform
    if t.b or t.d or abs(t.a - 1 / n) > 1e-9 or abs(t.e + 1 / n) > 1e-9:
        raise _unavailable(f"unexpected tile geometry {t}")
    col0_i = round((t.c + t.a / 2) * n)       # global lon index of column 0
    row0_j = round((t.f + t.e / 2) * n)       # global lat index of row 0 (northernmost)
    ny, nx = z.shape
    c_lo, c_hi = max(0, i0 - col0_i), min(src.width - 1, i0 + nx - 1 - col0_i)
    r_lo, r_hi = max(0, row0_j - (j0 + ny - 1)), min(src.height - 1, row0_j - j0)
    if c_lo > c_hi or r_lo > r_hi:
        return
    data = src.read(1, window=Window(c_lo, r_lo, c_hi - c_lo + 1, r_hi - r_lo + 1),
                    out_dtype="float64")
    if src.nodata is not None:
        data[data == src.nodata] = np.nan
    data[~np.isfinite(data)] = np.nan
    # AWS GLO-30: ocean is stored as exactly 0 m and the COGs carry no nodata value.
    data[data == COPERNICUS_SEA_VALUE] = np.nan
    y_hi = row0_j - r_lo - j0                 # z row of the window's first (northern) row
    y_lo = row0_j - r_hi - j0
    x_lo = col0_i + c_lo - i0
    z[y_lo:y_hi + 1, x_lo:x_lo + data.shape[1]] = data[::-1]


def fetch_copernicus(bbox: Bbox, settings: Settings) -> DemGrid:
    rasterio = _import_rasterio()
    from rasterio.errors import RasterioError, RasterioIOError

    n = COPERNICUS_POSTS_PER_DEG
    min_lon, min_lat, max_lon, max_lat = bbox
    i0, i1 = math.floor(min_lon * n), math.ceil(max_lon * n)
    j0, j1 = math.floor(min_lat * n), math.ceil(max_lat * n)
    z = np.full((j1 - j0 + 1, i1 - i0 + 1), np.nan)
    # A tile named N{a} holds lat posts (a, a+1]; E{b} holds lon posts [b, b+1).
    lat_tiles = range((j0 - 1) // n, (j1 - 1) // n + 1)
    lon_tiles = range(i0 // n, i1 // n + 1)
    base = settings.copernicus_base_url.rstrip("/")
    # GDAL caches /vsicurl results (including failures) for the life of the process; one
    # transient S3 error would otherwise fail, or blank out, every later job on that tile.
    with rasterio.Env(**COPERNICUS_GDAL_ENV, CPL_VSIL_CURL_NON_CACHED=f"/vsicurl/{base}"):
        for tlat in lat_tiles:
            for tlon in lon_tiles:
                name = copernicus_tile_name(tlat, tlon)
                url = f"{base}/{name}/{name}.tif"
                try:
                    with rasterio.open(url) as src:
                        _place_tile(src, z, i0, j0, n)
                except RasterioIOError as exc:
                    if _is_missing(exc, url):
                        # WARNING: a wrong COPERNICUS_BASE_URL also lands here.
                        log.warning("Copernicus tile %s not found at %s; treating it as ocean (no data)",
                                    name, base)
                        continue
                    raise _unavailable(f"reading {url}", exc) from exc
                except RasterioError as exc:
                    raise _unavailable(f"reading {url}", exc) from exc

    lons = np.arange(i0, i1 + 1) / n
    lats = np.arange(j0, j1 + 1) / n
    lons, lats, z = decimate(lons, lats, z, settings.max_grid_cells)
    return DemGrid(lons=lons, lats=lats, z=z, info={
        "provider": "copernicus",
        "name": COPERNICUS_NAME,
        "model_type": COPERNICUS_MODEL_TYPE,
        "epoch": COPERNICUS_EPOCH,
        "vertical_datum": COPERNICUS_VERTICAL_DATUM,
        "nominal_resolution_m": COPERNICUS_NOMINAL_RES_M,
        "attribution": COPERNICUS_ATTRIBUTION,
        "disclaimer": COPERNICUS_DISCLAIMER,
        "sends_coordinates_to_third_party": SENDS_COORDINATES["copernicus"],
    })


# ---------------------------------------------------------------------------
# opentopodata
# ---------------------------------------------------------------------------
def _otd_grid_shape(bbox: Bbox, max_points: int) -> tuple[int, int]:
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat, mid_lon = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
    w = max(GEOD.inv(min_lon, mid_lat, max_lon, mid_lat)[2], 1.0)
    h = max(GEOD.inv(mid_lon, min_lat, mid_lon, max_lat)[2], 1.0)
    spacing = math.sqrt(w * h / max_points)
    nx, ny = max(3, int(w / spacing) + 1), max(3, int(h / spacing) + 1)
    while nx * ny > max_points:
        if w / nx > h / ny:
            ny -= 1
        else:
            nx -= 1
    return nx, ny


def _otd_post(session, url: str, payload: dict, sleep: Callable[[float], None]) -> dict:
    import requests

    last: BaseException | None = None
    for attempt in (1, 2):
        try:
            resp = session.post(url, json=payload, timeout=OTD_TIMEOUT_S)
            if resp.status_code == 429 or resp.status_code >= 500:
                last = RuntimeError(f"HTTP {resp.status_code}")
            elif resp.status_code != 200:
                raise _unavailable(f"OpenTopoData HTTP {resp.status_code}")
            else:
                body = resp.json()
                if body.get("status") != "OK":
                    raise _unavailable(f"OpenTopoData status {body.get('status')!r}")
                return body
        except requests.RequestException as exc:
            last = exc
        except ValueError as exc:   # invalid JSON
            raise _unavailable("OpenTopoData returned invalid JSON", exc) from exc
        if attempt == 1:
            sleep(OTD_RETRY_WAIT_S)
    raise _unavailable(f"OpenTopoData {url}", last)


def fetch_opentopodata(bbox: Bbox, settings: Settings, *, session=None,
                       sleep: Callable[[float], None] = time.sleep) -> DemGrid:
    import requests

    nx, ny = _otd_grid_shape(bbox, OTD_MAX_POINTS)
    min_lon, min_lat, max_lon, max_lat = bbox
    lons = np.linspace(min_lon, max_lon, nx)
    lats = np.linspace(min_lat, max_lat, ny)
    lon_g, lat_g = np.meshgrid(lons, lats)
    locs = list(zip(lat_g.ravel(), lon_g.ravel()))
    url = f"{settings.opentopodata_url.rstrip('/')}/{settings.opentopodata_dataset}"
    own = session is None
    session = session or requests.Session()
    values: list[float] = []
    try:
        for k in range(0, len(locs), OTD_BATCH):
            if k:
                sleep(OTD_CALL_INTERVAL_S)       # public API: max 1 call per second
            batch = locs[k:k + OTD_BATCH]
            payload = {"locations": "|".join(f"{la:.6f},{lo:.6f}" for la, lo in batch),
                       "interpolation": "bilinear"}
            results = _otd_post(session, url, payload, sleep).get("results") or []
            if len(results) != len(batch):
                raise _unavailable("OpenTopoData returned the wrong number of results")
            for r in results:
                v = r.get("elevation")
                values.append(float(v) if v is not None else np.nan)
    finally:
        if own:
            session.close()
    z = np.asarray(values, dtype=np.float64).reshape(ny, nx)
    return DemGrid(lons=lons, lats=lats, z=z, info={
        "provider": "opentopodata",
        "name": SRTM_NAME,
        "model_type": SRTM_MODEL_TYPE,
        "epoch": SRTM_EPOCH,
        "vertical_datum": SRTM_VERTICAL_DATUM,
        "nominal_resolution_m": SRTM_NOMINAL_RES_M,
        "attribution": SRTM_ATTRIBUTION,
        "disclaimer": None,
        "sends_coordinates_to_third_party": SENDS_COORDINATES["opentopodata"],
    })


# ---------------------------------------------------------------------------
# local GeoTIFF / VRT
# ---------------------------------------------------------------------------
# Cells read at once while block-averaging a large GeoTIFF window (bounds memory to a strip).
GEOTIFF_STRIP_CELLS = 1_000_000


def _read_window_decimated(src, c_lo: int, r_lo: int, ncols: int, nrows: int, max_cells: int):
    """Read a window as a float64 grid (NaN = no data) in raster order, block-averaged to fit
    max_cells exactly as decimate() would after flipping to ascending axes, but strip by strip,
    so a high-resolution file never has the whole window in memory. Returns (z, lons, lats)."""
    from rasterio.windows import Window

    t = src.transform
    k = decimation_factor(nrows, ncols, max_cells)
    ry, rx = nrows % k, ncols % k
    # decimate() trims (r // 2) at the low end of each ascending axis; mirror that in raster order.
    r0 = r_lo + (ry - ry // 2 if t.e < 0 else ry // 2)
    c0 = c_lo + (rx // 2 if t.a > 0 else rx - rx // 2)
    nby, nbx = nrows // k, ncols // k
    z = np.empty((nby, nbx), dtype=np.float64)
    step = max(1, GEOTIFF_STRIP_CELLS // (k * k * nbx))
    for b in range(0, nby, step):
        nb = min(step, nby - b)
        data = src.read(1, window=Window(c0, r0 + b * k, nbx * k, nb * k), out_dtype="float64",
                        masked=True)
        strip = np.ma.filled(data, np.nan)
        strip[~np.isfinite(strip)] = np.nan
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)   # all-NaN blocks stay NaN
            z[b:b + nb] = np.nanmean(strip.reshape(nb, k, nbx, k), axis=(1, 3))
    lons = t.c + (c0 + (np.arange(nbx) + 0.5) * k) * t.a
    lats = t.f + (r0 + (np.arange(nby) + 0.5) * k) * t.e
    return z, lons, lats


def fetch_geotiff(bbox: Bbox, settings: Settings) -> DemGrid:
    rasterio = _import_rasterio()
    from rasterio.errors import RasterioError

    path = settings.dem_geotiff_path
    if not path:
        raise _unavailable("DEM_PROVIDER=geotiff but DEM_GEOTIFF_PATH is empty")
    min_lon, min_lat, max_lon, max_lat = bbox
    try:
        with rasterio.open(path) as src:
            if src.crs is None or src.crs.to_epsg() != 4326:
                raise _unavailable(f"{path} is not EPSG:4326 (crs={src.crs})")
            t = src.transform
            if t.b or t.d:
                raise _unavailable(f"{path} has a rotated geotransform")
            # Column/row (fractional, centre-based) of the bbox edges, widened by one cell.
            cols = sorted(((min_lon - t.c) / t.a - 0.5, (max_lon - t.c) / t.a - 0.5))
            rows = sorted(((max_lat - t.f) / t.e - 0.5, (min_lat - t.f) / t.e - 0.5))
            c_lo, c_hi = max(0, math.floor(cols[0])), min(src.width - 1, math.ceil(cols[1]))
            r_lo, r_hi = max(0, math.floor(rows[0])), min(src.height - 1, math.ceil(rows[1]))
            if c_hi - c_lo < 2 or r_hi - r_lo < 2:
                raise ScreeningError(NO_COVERAGE_MESSAGE, "no_dem_coverage")
            z, lons, lats = _read_window_decimated(src, c_lo, r_lo, c_hi - c_lo + 1, r_hi - r_lo + 1,
                                                   settings.max_grid_cells)
            res_deg = (abs(t.a) + abs(t.e)) / 2
    except RasterioError as exc:
        raise _unavailable(f"reading {path}", exc) from exc
    if lons[0] > lons[-1]:
        lons, z = lons[::-1], z[:, ::-1]
    if lats[0] > lats[-1]:
        lats, z = lats[::-1], z[::-1, :]
    z = np.ascontiguousarray(z)
    mid_lat = (min_lat + max_lat) / 2
    res_m = GEOD.inv(0.0, mid_lat, 0.0, mid_lat + res_deg)[2]
    info = {
        "provider": "geotiff",
        "name": GEOTIFF_NAME,
        "model_type": GEOTIFF_MODEL_TYPE,
        "epoch": GEOTIFF_EPOCH,
        "vertical_datum": GEOTIFF_VERTICAL_DATUM,
        "nominal_resolution_m": max(1, round(res_m)),
        "attribution": GEOTIFF_ATTRIBUTION,
        "disclaimer": None,
        "sends_coordinates_to_third_party": SENDS_COORDINATES["geotiff"],
    }
    info.update(settings.extra.get("dem_geotiff_info", {}) if settings.extra else {})
    return DemGrid(lons=lons, lats=lats, z=z, info=info)


# ---------------------------------------------------------------------------
PROVIDERS: dict[str, DemFetcher] = {
    "copernicus": fetch_copernicus,
    "opentopodata": fetch_opentopodata,
    "geotiff": fetch_geotiff,
}


def fetch_dem(bbox: Bbox, settings: Settings) -> DemGrid:
    """Fetch a DEM grid covering bbox with the provider named in settings.dem_provider."""
    try:
        provider = PROVIDERS[settings.dem_provider]
    except KeyError:
        raise ValueError(f"Unknown DEM_PROVIDER {settings.dem_provider!r}; "
                         f"expected one of {sorted(PROVIDERS)}") from None
    return provider(bbox, settings)
