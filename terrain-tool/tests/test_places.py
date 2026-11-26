"""Key location snapshot (app/places.py): reference towns, distance and bearing, extent and the
wording shared by summary.md, the result page and the PDF/Word reports. No network."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import places  # noqa: E402

LANGKAWI = (99.70004, 6.38950)          # centroid of the Langkawi site the snapshot was built for


def test_langkawi_site_is_west_north_west_of_kuah():
    first, second = places.nearest_towns(*LANGKAWI)
    assert (first["name"], first["state"], first["bearing"]) == ("Kuah", "Kedah", "WNW")
    assert 16.5 < first["distance_km"] < 18.5          # OSM puts Kuah's centre 17.9 km away
    assert (second["name"], second["bearing"]) == ("Kangar", "W")
    assert places.town_phrase(first) == "≈ 17 km WNW of Kuah, Kedah"


@pytest.mark.parametrize("azimuth, name", [(0, "N"), (11.2, "N"), (11.3, "NNE"), (45, "NE"),
                                           (90, "E"), (180, "S"), (-90, "W"), (270, "W"),
                                           (292.5, "WNW"), (348.7, "NNW"), (348.8, "N"),
                                           (359.9, "N"), (720, "N")])
def test_compass16(azimuth, name):
    assert places.compass16(azimuth) == name


def test_bearing_is_from_the_town_to_the_site():
    """A site due north of Kuantan reads "N of Kuantan", not the reverse direction."""
    town = next(t for t in places.TOWNS if t[0] == "Kuantan")
    (near,) = places.nearest_towns(town[3], town[2] + 0.05, n=1)
    assert near["name"] == "Kuantan" and near["bearing"] == "N"


@pytest.mark.parametrize("km, text", [(None, "—"), (0.4, "< 1 km"), (1.0, "≈ 1.0 km"),
                                      (4.24, "≈ 4.2 km"), (9.96, "≈ 10 km"), (17.3, "≈ 17 km"),
                                      (1234.0, "≈ 1,234 km")])
def test_distance_text(km, text):
    assert places.distance_text(km) == text


def test_town_phrase_names_the_state_once():
    kl = {"name": "Kuala Lumpur", "state": "W.P. Kuala Lumpur", "distance_km": 0.4, "bearing": "N"}
    assert places.town_phrase(kl) == "in Kuala Lumpur"
    assert places.town_phrase(dict(kl, distance_km=5.0)) == "≈ 5.0 km N of Kuala Lumpur"
    assert places.town_phrase({"name": "Melaka", "state": "Melaka", "distance_km": 12, "bearing": "E"}) \
        == "≈ 12 km E of Melaka"
    assert places.town_phrase({"name": "Ipoh", "state": "Perak", "distance_km": None}) == "Ipoh, Perak"
    assert places.town_phrase(None) == "" and places.town_phrase({}) == ""


def test_extent_is_geodesic_through_the_centroid():
    # 0.01° of longitude at the equator is 1.113 km; 0.01° of latitude is 1.106 km
    ext = places.extent_km((101.0, -0.005, 101.01, 0.005), (101.005, 0.0))
    assert ext == {"ew": 1.11, "ns": 1.11}
    # at 6.4° N a degree of longitude is shorter by cos(lat)
    ext = places.extent_km((99.69, 6.38, 99.71, 6.40), (99.70, 6.39))
    assert 2.18 < ext["ew"] < 2.23 and 2.19 < ext["ns"] < 2.23


def test_town_list_is_sound():
    names = [t[0] for t in places.TOWNS]
    assert len(names) == len(set(names)) == 55
    states = {t[1] for t in places.TOWNS}
    assert {"Perlis", "Kedah", "Pulau Pinang", "Perak", "Selangor", "W.P. Kuala Lumpur",
            "W.P. Putrajaya", "Negeri Sembilan", "Melaka", "Johor", "Pahang", "Terengganu",
            "Kelantan", "Sabah", "Sarawak", "W.P. Labuan"} <= states        # every state and FT
    for name, state, lat, lon in places.TOWNS:
        assert 0.8 < lat < 7.5 and 99.5 < lon < 119.5, name


def test_town_states_match_the_tools_own_boundary_lookup():
    from app.terrain import boundaries
    for name, state, lat, lon in places.TOWNS:
        if state != "Singapore":
            assert boundaries.lookup(lon, lat)[0] == state, name


def test_snapshot_wording_from_a_current_result():
    result = {"location": {"centroid_lon": LANGKAWI[0], "centroid_lat": LANGKAWI[1],
                           "nearest_towns": places.nearest_towns(*LANGKAWI)},
              "totals": {"polygon_count": 1, "total_area_ha": 120.58,
                         "extent_km": {"ew": 2.21, "ns": 1.67}}}
    snap = places.snapshot(result)
    assert snap["centroid"] == "6.38950° N, 99.70004° E"
    assert snap["size"] == ("1 site · 120.58 ha (1.21 km²) · overall extent ≈ 2.2 km E–W × "
                            "1.7 km N–S")
    assert snap["nearest"] == ("≈ 17 km WNW of Kuah, Kedah (next: ≈ 56 km W of Kangar, Perlis); "
                               "straight-line, not road distance")


def test_snapshot_of_an_older_result_recomputes_towns_and_skips_the_extent():
    result = {"location": {"centroid_lon": LANGKAWI[0], "centroid_lat": LANGKAWI[1]},
              "totals": {"polygon_count": 3, "total_area_ha": 12.5}}
    snap = places.snapshot(result)
    assert snap["size"] == "3 sites · 12.50 ha (0.12 km²)"
    assert snap["nearest"].startswith("≈ 17 km WNW of Kuah, Kedah")


def test_snapshot_tolerates_missing_and_bad_values():
    assert places.snapshot({}) == {"centroid": "—", "size": "—", "nearest": "—"}
    bad = {"location": {"centroid_lon": "x", "centroid_lat": None, "nearest_towns": ["junk", None]},
           "totals": {"polygon_count": True, "total_area_ha": "big", "extent_km": {"ew": None}}}
    assert places.snapshot(bad) == {"centroid": "—", "size": "—", "nearest": "—"}
    south_west = {"location": {"centroid_lon": -0.5, "centroid_lat": -1.25, "nearest_towns": []}}
    assert places.snapshot(south_west)["centroid"] == "1.25000° S, 0.50000° W"


def test_places_loads_neither_the_engine_nor_pyproj():
    """The web app and the report renderers import app.places directly; it must not pull in
    the terrain engine (loaded lazily, replaced by a fake in the flow tests) and only loads
    pyproj when a distance is computed."""
    code = ("import sys, json; import app.places as p; "
            "p.snapshot({'location': {'nearest_towns': []}}); "
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith(('app.terrain', 'pyproj')))))")
    out = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT, capture_output=True,
                         text=True, check=True).stdout
    assert json.loads(out) == []


def test_town_credit():
    assert places.town_credit({}) is None                           # no centroid, no towns
    assert places.town_credit({"location": {"town_attribution": "Stored credit."}}) == "Stored credit."
    older = {"location": {"centroid_lon": LANGKAWI[0], "centroid_lat": LANGKAWI[1]}}
    assert places.town_credit(older) == places.TOWN_ATTRIBUTION
