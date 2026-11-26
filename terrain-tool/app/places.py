"""Reference towns for the key location snapshot.

Every land description opens with where the site is: its centroid, its overall size and
extent, and its straight-line distance and compass direction from the nearest major town.
Towns are the state and federal-territory capitals, the principal regional towns and
Singapore; positions are GeoNames town points (geonames.org, CC BY 4.0), checked against
OpenStreetMap to within a few kilometres, and each town's state is the tool's own DOSM
district lookup. Distances are geodesic on the WGS 84 ellipsoid, not road distances.
"""
from __future__ import annotations

from functools import lru_cache

# Deliberately free of the terrain engine: the web app and the report renderers import this
# module directly (the engine itself is loaded lazily), and pyproj is only loaded when a
# distance has to be computed.


@lru_cache(maxsize=1)
def _geod():
    from pyproj import Geod
    return Geod(ellps="WGS84")


TOWN_ATTRIBUTION = ("Reference towns: GeoNames (geonames.org), licensed under CC BY 4.0; "
                    "distances are straight-line (geodesic), not road distances.")

COMPASS16 = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")

# (name, state as DOSM spells it, latitude, longitude)
TOWNS: tuple[tuple[str, str, float, float], ...] = (
    ("Kangar", "Perlis", 6.4414, 100.1986),
    ("Alor Setar", "Kedah", 6.1210, 100.3601),
    ("Sungai Petani", "Kedah", 5.6470, 100.4877),
    ("Kulim", "Kedah", 5.3650, 100.5618),
    ("Kuah", "Kedah", 6.3265, 99.8432),
    ("George Town", "Pulau Pinang", 5.4112, 100.3354),
    ("Butterworth", "Pulau Pinang", 5.3991, 100.3638),
    ("Ipoh", "Perak", 4.5841, 101.0829),
    ("Taiping", "Perak", 4.8500, 100.7333),
    ("Teluk Intan", "Perak", 4.0222, 101.0208),
    ("Sitiawan", "Perak", 4.2168, 100.6996),
    ("Shah Alam", "Selangor", 3.0851, 101.5328),
    ("Klang", "Selangor", 3.0367, 101.4433),
    ("Kuala Lumpur", "W.P. Kuala Lumpur", 3.1412, 101.6865),
    ("Putrajaya", "W.P. Putrajaya", 2.9353, 101.6911),
    ("Seremban", "Negeri Sembilan", 2.7297, 101.9381),
    ("Port Dickson", "Negeri Sembilan", 2.5246, 101.7965),
    ("Melaka", "Melaka", 2.1960, 102.2405),
    ("Johor Bahru", "Johor", 1.4655, 103.7578),
    ("Batu Pahat", "Johor", 1.8548, 102.9325),
    ("Muar", "Johor", 2.0442, 102.5689),
    ("Kluang", "Johor", 2.0305, 103.3169),
    ("Segamat", "Johor", 2.5148, 102.8158),
    ("Kota Tinggi", "Johor", 1.7381, 103.8999),
    ("Mersing", "Johor", 2.4312, 103.8405),
    ("Pontian Kechil", "Johor", 1.4866, 103.3896),
    ("Kuantan", "Pahang", 3.8077, 103.3260),
    ("Temerloh", "Pahang", 3.4506, 102.4176),
    ("Bentong", "Pahang", 3.5316, 101.9038),
    ("Raub", "Pahang", 3.7899, 101.8570),
    ("Kuala Lipis", "Pahang", 4.1842, 102.0468),
    ("Jerantut", "Pahang", 3.9360, 102.3626),
    ("Pekan", "Pahang", 3.4836, 103.3996),
    ("Kuala Rompin", "Pahang", 2.8167, 103.4833),
    ("Kuala Terengganu", "Terengganu", 5.3302, 103.1408),
    ("Chukai", "Terengganu", 4.2500, 103.4167),
    ("Kuala Dungun", "Terengganu", 4.7750, 103.4162),
    ("Kota Bharu", "Kelantan", 6.1236, 102.2433),
    ("Kuala Krai", "Kelantan", 5.5313, 102.1993),
    ("Gua Musang", "Kelantan", 4.8844, 101.9686),
    ("Kota Kinabalu", "Sabah", 5.9749, 116.0724),
    ("Sandakan", "Sabah", 5.8402, 118.1179),
    ("Tawau", "Sabah", 4.2448, 117.8911),
    ("Lahad Datu", "Sabah", 5.0230, 118.3290),
    ("Keningau", "Sabah", 5.3378, 116.1602),
    ("Kudat", "Sabah", 6.8873, 116.8236),
    ("Labuan", "W.P. Labuan", 5.2803, 115.2475),
    ("Kuching", "Sarawak", 1.5500, 110.3333),
    ("Sri Aman", "Sarawak", 1.2472, 111.4528),
    ("Sibu", "Sarawak", 2.3000, 111.8167),
    ("Kapit", "Sarawak", 1.9955, 112.9325),
    ("Bintulu", "Sarawak", 3.1667, 113.0333),
    ("Miri", "Sarawak", 4.3993, 113.9916),
    ("Limbang", "Sarawak", 4.7548, 115.0101),
    ("Singapore", "Singapore", 1.2897, 103.8501),
)


def compass16(azimuth_deg: float) -> str:
    """16-point compass name for an azimuth in degrees (0 = north, clockwise)."""
    return COMPASS16[round((azimuth_deg % 360.0) / 22.5) % 16]


def nearest_towns(lon: float, lat: float, n: int = 2) -> list[dict]:
    """The n towns nearest to (lon, lat), nearest first. `bearing` is the direction of the
    site as seen from the town, so a row reads "about 17 km WNW of Kuah"."""
    ranked = []
    for name, state, t_lat, t_lon in TOWNS:
        azimuth, _, dist_m = _geod().inv(t_lon, t_lat, lon, lat)
        ranked.append({"name": name, "state": state, "distance_km": round(dist_m / 1000.0, 1),
                       "bearing": compass16(azimuth)})
    ranked.sort(key=lambda t: t["distance_km"])
    return ranked[:n]


def extent_km(bbox: tuple[float, float, float, float], centroid: tuple[float, float]) -> dict:
    """Overall east-west and north-south extent of all features, in km: the width of the
    bounding box measured along the centroid's latitude and its height along its longitude."""
    min_lon, min_lat, max_lon, max_lat = bbox
    lon, lat = centroid
    ew = _geod().inv(min_lon, lat, max_lon, lat)[2] / 1000.0
    ns = _geod().inv(lon, min_lat, lon, max_lat)[2] / 1000.0
    return {"ew": round(ew, 2), "ns": round(ns, 2)}


def distance_text(km: float | None) -> str:
    """'≈ 18 km' (whole km from 10 km up), '≈ 4.2 km' below that, '< 1 km' when very close."""
    if km is None:
        return "—"
    if km < 1:
        return "< 1 km"
    km = round(km, 1)                       # 9.96 reads "≈ 10 km", not "≈ 10.0 km"
    return f"≈ {km:,.0f} km" if km >= 10 else f"≈ {km:.1f} km"


def town_phrase(town: dict | None) -> str:
    """'≈ 17 km WNW of Kuah, Kedah' for one entry of nearest_towns()."""
    if not town or not town.get("name"):
        return ""
    # "Kuala Lumpur", not "Kuala Lumpur, W.P. Kuala Lumpur"; likewise Melaka, Labuan, Singapore.
    state = town.get("state") or ""
    where = town["name"] if not state or town["name"] in state else f"{town['name']}, {state}"
    km = town.get("distance_km")
    if km is None:
        return where
    if km < 1:
        return f"in {where}"
    bearing = f" {town['bearing']}" if town.get("bearing") else ""
    return f"{distance_text(km)}{bearing} of {where}"


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def centroid_text(lon: float, lat: float) -> str:
    """'6.38950° N, 99.70004° E' (5 decimals: about 1 m)."""
    return f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.5f}° {'E' if lon >= 0 else 'W'}"


def map_line(lon: float, lat: float) -> str:
    """One short line for the site layout map: centroid and nearest town."""
    towns = nearest_towns(lon, lat, n=1)
    near = f" · {town_phrase(towns[0])} (straight line)" if towns else ""
    return f"Centroid {centroid_text(lon, lat)}{near}"


def town_credit(result: dict) -> str | None:
    """The GeoNames credit (CC BY 4.0) whenever the snapshot names a town: as stored, or the
    current wording for a result.json written before the field existed."""
    stored = (result.get("location") or {}).get("town_attribution")
    if isinstance(stored, str) and stored.strip():
        return stored
    return TOWN_ATTRIBUTION if snapshot(result)["nearest"] != "—" else None


def snapshot(result: dict) -> dict[str, str]:
    """The key location snapshot as three lines (centroid, size, nearest town), worded once
    for the PDF, Word, result page and summary.md. Tolerates result.json files written before
    these fields existed: nearest towns are recomputed from the centroid and a missing
    extent is left out."""
    loc, tot = result.get("location") or {}, result.get("totals") or {}
    lat, lon = loc.get("centroid_lat"), loc.get("centroid_lon")
    have_centroid = _number(lat) and _number(lon)
    centroid = centroid_text(lon, lat) if have_centroid else "—"

    size = []
    n = tot.get("polygon_count")
    if _number(n) and n > 0:
        size.append(f"{int(n)} site{'s' if n != 1 else ''}")
    area = tot.get("total_area_ha")
    if _number(area) and area > 0:
        size.append(f"{area:,.2f} ha ({area / 100:,.2f} km²)")
    ext = tot.get("extent_km") or {}
    if _number(ext.get("ew")) and _number(ext.get("ns")):
        size.append(f"overall extent ≈ {ext['ew']:,.1f} km E–W × {ext['ns']:,.1f} km N–S")

    towns = loc.get("nearest_towns")
    if towns is None and have_centroid:  # result.json written before the snapshot existed
        try:
            towns = nearest_towns(lon, lat)
        except Exception:  # noqa: BLE001 - a missing snapshot must never stop a report
            towns = None
    towns = [t for t in (towns or []) if isinstance(t, dict)]
    nearest = town_phrase(towns[0]) if towns else ""
    if nearest and len(towns) > 1 and town_phrase(towns[1]):
        nearest += f" (next: {town_phrase(towns[1])})"
    if nearest:
        nearest += "; straight-line, not road distance"
    return {"centroid": centroid, "size": " · ".join(size) or "—", "nearest": nearest or "—"}
