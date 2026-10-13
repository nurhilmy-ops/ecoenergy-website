"""KML/KMZ parsing and validation matrix for app.terrain.validate_upload."""
from __future__ import annotations

import io
import struct
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine_helpers import (FIXTURES, kml_doc, line_pm, make_settings, offset,  # noqa: E402
                            point_pm, polygon_pm, rect, write)

from app.terrain import ScreeningError, validate_upload  # noqa: E402
from app.terrain.kml import _read_capped, clean_text  # noqa: E402

LON, LAT = 101.5, 3.5
SQUARE = rect(LON, LAT, 300, 300)


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


def parse(tmp_path, text, settings, name="site.kml"):
    return validate_upload(write(tmp_path, name, text), settings, name)


def code_of(excinfo) -> str:
    return excinfo.value.code


def make_kmz(members: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# namespaces and geometry types
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ns", [
    "http://www.opengis.net/kml/2.2",
    "http://earth.google.com/kml/2.1",
    "http://earth.google.com/kml/2.0",
    None,
])
def test_namespaces_accepted(tmp_path, settings, ns):
    body = polygon_pm("Lot 1", SQUARE) + line_pm("Cable", [SQUARE[1], offset(LON, LAT, 900, 0)]) \
        + point_pm("PMU", offset(LON, LAT, 900, 0))
    site = parse(tmp_path, kml_doc(body, ns=ns), settings)
    assert [(f.name, f.kind) for f in site.features] == [
        ("Lot 1", "polygon"), ("Cable", "line"), ("PMU", "point")]
    poly = site.features[0]
    assert len(poly.coords) == 4                       # open ring, altitude dropped
    assert all(len(c) == 2 for c in poly.coords)
    assert site.bbox[0] == pytest.approx(LON) and site.bbox[1] == pytest.approx(LAT)
    assert 0.85 < site.extent_km < 0.95
    assert site.source_filename == "site.kml"


def test_prefixed_kml_namespace(tmp_path, settings):
    body = polygon_pm("Prefixed", SQUARE, prefix="kml:")
    text = ('<?xml version="1.0"?><kml:kml xmlns:kml="http://www.opengis.net/kml/2.2">'
            f"<kml:Document>{body}</kml:Document></kml:kml>")
    site = parse(tmp_path, text, settings)
    assert site.features[0].name == "Prefixed"


def test_foreign_namespace_is_not_kml(tmp_path, settings):
    text = ('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg">'
            "<Placemark><Point><coordinates>101.5,3.5</coordinates></Point></Placemark></svg>")
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, text, settings)
    assert code_of(e) == "invalid_kml"


def test_multigeometry_split_into_parts(tmp_path, settings):
    a = rect(LON, LAT, 200, 200)
    b = rect(*offset(LON, LAT, 400, 0), 200, 200)
    def poly(r):
        coords = " ".join(f"{x},{y},0" for x, y in r + [r[0]])
        return (f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}</coordinates>"
                "</LinearRing></outerBoundaryIs></Polygon>")
    link = f"{a[1][0]},{a[1][1]} {b[0][0]},{b[0][1]}"
    pm = (f"<Placemark><name>Farm</name><MultiGeometry>{poly(a)}{poly(b)}"
          f"<MultiGeometry><LineString><coordinates>{link}</coordinates></LineString></MultiGeometry>"
          "</MultiGeometry></Placemark>")
    site = parse(tmp_path, kml_doc(pm), settings)
    assert [(f.name, f.kind) for f in site.features] == [
        ("Farm (part 1)", "polygon"), ("Farm (part 2)", "polygon"), ("Farm", "line")]


def test_polygon_with_holes(tmp_path, settings):
    outer = rect(LON, LAT, 600, 600)
    holes = [rect(*offset(LON, LAT, 100, 100), 100, 100), rect(*offset(LON, LAT, 350, 350), 100, 100)]
    site = parse(tmp_path, kml_doc(polygon_pm("Holey", outer, holes)), settings)
    f = site.features[0]
    assert len(f.holes) == 2 and all(len(h) == 4 for h in f.holes)


def test_several_rings_in_one_inner_boundary(tmp_path, settings):
    outer = rect(LON, LAT, 600, 600)
    h1, h2 = rect(*offset(LON, LAT, 100, 100), 80, 80), rect(*offset(LON, LAT, 300, 300), 80, 80)
    ring = lambda r: " ".join(f"{x},{y}" for x, y in r + [r[0]])  # noqa: E731
    pm = ("<Placemark><Polygon><outerBoundaryIs>"
          f"<LinearRing><coordinates>{ring(outer)}</coordinates></LinearRing></outerBoundaryIs>"
          f"<innerBoundaryIs><LinearRing><coordinates>{ring(h1)}</coordinates></LinearRing>"
          f"<LinearRing><coordinates>{ring(h2)}</coordinates></LinearRing></innerBoundaryIs>"
          "</Polygon></Placemark>")
    site = parse(tmp_path, kml_doc(pm), settings)
    assert len(site.features[0].holes) == 2


def test_default_names(tmp_path, settings):
    body = (polygon_pm(None, SQUARE) + polygon_pm("", rect(*offset(LON, LAT, 400, 0), 100, 100))
            + line_pm(None, [SQUARE[0], SQUARE[2]]) + point_pm(None, SQUARE[0]))
    site = parse(tmp_path, kml_doc(body), settings)
    assert [f.name for f in site.features] == ["Site 1", "Site 2", "Route 1", "Point 1"]


def test_names_are_sanitised(tmp_path, settings):
    # XML 1.0 forbids most C0 controls, but C1 controls (U+0085), bidi overrides and
    # zero-width characters are legal XML and must still be stripped.
    nasty = "Lot‮ ev​il\u0085 \t name " + "x" * 200
    site = parse(tmp_path, kml_doc(point_pm(nasty, SQUARE[0])), settings)
    name = site.features[0].name
    assert len(name) <= 80
    assert not any(c in name for c in "‮​\u0085\t")
    assert name.startswith("Lot evil name")


def test_clean_text_helper():
    assert clean_text("  a\x00b \n c  ") == "ab c"
    assert clean_text(None) == ""
    assert len(clean_text("y" * 100)) == 80


def test_coordinate_tokenizing_is_robust(tmp_path, settings):
    pts = SQUARE + [SQUARE[0]]
    messy = "\n\t ".join(f"{x:.6f} , {y:.6f} ,  12.5" for x, y in pts[:2]) + "\n" + \
        "   ".join(f"{x:.6f},{y:.6f}" for x, y in pts[2:]) + "  \n"
    pm = ("<Placemark><name>Messy</name><Polygon><outerBoundaryIs><LinearRing><coordinates>"
          f"{messy}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>")
    site = parse(tmp_path, kml_doc(pm), settings)
    assert len(site.features[0].coords) == 4
    assert site.features[0].coords[0] == pytest.approx(SQUARE[0])


@pytest.mark.parametrize("coords", ["101.5", "abc,3.5", "101.5,nan", "101.5,inf 101.6,3.5"])
def test_bad_coordinates(tmp_path, settings, coords):
    pm = (f"<Placemark><name>Bad</name><LineString><coordinates>{coords}</coordinates>"
          "</LineString></Placemark>")
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(pm), settings)
    assert code_of(e) == "invalid_coordinates"


def test_uppercase_extension(tmp_path, settings):
    site = parse(tmp_path, kml_doc(point_pm("P", SQUARE[0])), settings, name="SITE.KML")
    assert site.features[0].kind == "point"


# ---------------------------------------------------------------------------
# geometry validation
# ---------------------------------------------------------------------------
def test_polygon_needs_three_distinct_vertices(tmp_path, settings):
    a, b = SQUARE[0], SQUARE[1]
    pm = polygon_pm("Thin", [a, b, a])
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(pm), settings)
    assert code_of(e) == "invalid_polygon"


def test_zero_area_polygon_rejected(tmp_path, settings):
    a, c = SQUARE[0], offset(LON, LAT, 300, 0)
    mid = offset(LON, LAT, 150, 0)
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(polygon_pm("Flat", [a, mid, c])), settings)
    assert code_of(e) == "invalid_polygon"


def test_self_intersection_is_repaired(tmp_path, settings):
    # Bow-tie: two triangles of different size; the larger one is kept.
    from shapely.geometry import Polygon

    ring = [offset(LON, LAT, 0, 0), offset(LON, LAT, 400, 400),
            offset(LON, LAT, 400, 0), offset(LON, LAT, 0, 600)]
    assert not Polygon(ring).is_valid
    site = parse(tmp_path, kml_doc(polygon_pm("Bowtie", ring)), settings)
    assert site.repaired == ["Bowtie"]
    poly = Polygon(site.features[0].coords, site.features[0].holes)
    import shapely
    parts = shapely.make_valid(Polygon(ring)).geoms
    assert poly.is_valid and poly.area == pytest.approx(max(g.area for g in parts), rel=1e-3)


def _star(n: int, radius_deg: float = 0.015):
    """A {n/(n//2)} star polygon: every edge crosses most of the others."""
    import math
    k = n // 2
    return [(LON + radius_deg * math.cos(2 * math.pi * i * k / n),
             LAT + radius_deg * math.sin(2 * math.pi * i * k / n)) for i in range(n)]


def test_heavily_self_intersecting_polygon_is_refused_quickly(tmp_path, settings):
    """appsec-2: make_valid on a star polygon costs minutes of CPU (about n^3); a few KB of
    KML must not tie up a worker thread. Such boundaries are refused before any repair."""
    import time

    t0 = time.monotonic()
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(polygon_pm("Star", _star(401))), settings)
    assert code_of(e) == "too_complex" and "crosses itself" in e.value.message
    assert time.monotonic() - t0 < 2.0
    # An invalid polygon with more vertices than a repair can safely handle is refused too.
    import math
    ring = [(LON + 0.01 * math.cos(2 * math.pi * i / 2500), LAT + 0.01 * math.sin(2 * math.pi * i / 2500))
            for i in range(2500)]
    ring[10], ring[1260] = ring[1260], ring[10]                # one slip across the boundary
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(polygon_pm("Big slip", ring)), settings)
    assert code_of(e) == "too_complex"


def test_a_few_self_intersections_are_still_repaired(tmp_path, settings):
    import math
    ring = [(LON + 0.01 * math.cos(2 * math.pi * i / 400), LAT + 0.01 * math.sin(2 * math.pi * i / 400))
            for i in range(400)]
    for i in (10, 110, 210):                                    # three digitising slips
        ring[i], ring[i + 3] = ring[i + 3], ring[i]
    site = parse(tmp_path, kml_doc(polygon_pm("Slips", ring)), settings)
    assert site.repaired == ["Slips"]


def test_total_route_length_is_capped(tmp_path, settings):
    """appsec-3: a zig-zag line inside the extent limit can be hundreds of thousands of km long
    and is densified every ~30 m; total line length is bounded at validation."""
    a, b = (101.40, 3.40), (101.53, 3.41)                       # ~14.5 km apart
    zigzag = [a if i % 2 == 0 else b for i in range(40)]        # ~565 km
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(line_pm("Cable", zigzag)), settings)
    assert code_of(e) == "too_complex" and "routes in this file add up to" in e.value.message
    ok = parse(tmp_path, kml_doc(line_pm("Cable", zigzag[:10])), settings)   # ~130 km: fine
    assert ok.features[0].kind == "line"


def test_xml_with_too_many_elements_is_refused_while_parsing(tmp_path, settings, monkeypatch):
    """appsec-4: a ~20 KB KMZ can hold millions of empty elements; the parse stops at a cap
    instead of building the whole tree in memory."""
    from app.terrain import kml

    calls = []
    original = kml.DET.iterparse

    def counting_iterparse(*args, **kwargs):
        for item in original(*args, **kwargs):
            calls.append(1)
            yield item

    monkeypatch.setattr(kml.DET, "iterparse", counting_iterparse)
    body = "<a/>" * 2_000_000                                  # 8 MB uncompressed
    kmz = make_kmz({"doc.kml": kml_doc(body)})
    assert len(kmz) < 100_000
    with pytest.raises(ScreeningError) as e:
        validate_upload(write(tmp_path, "bomb.kmz", kmz), settings, "bomb.kmz")
    assert code_of(e) == "too_complex"
    assert len(calls) == kml.MAX_XML_ELEMENTS + 1               # stopped at the cap


def test_line_needs_two_distinct_points(tmp_path, settings):
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(line_pm("Dot", [SQUARE[0], SQUARE[0]])), settings)
    assert code_of(e) == "invalid_line"


def test_outside_malaysia(tmp_path, settings):
    jakarta = rect(106.8, -6.2, 300, 300)
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(polygon_pm("Jakarta", jakarta)), settings)
    assert code_of(e) == "outside_malaysia"


def test_swapped_coordinates_hint(tmp_path, settings):
    pm = "<Placemark><Point><coordinates>3.1,101.7</coordinates></Point></Placemark>"
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(pm), settings)
    assert code_of(e) == "outside_malaysia"
    assert "swapped" in e.value.message


def test_hole_coordinates_also_checked(tmp_path, settings):
    outer = rect(LON, LAT, 600, 600)
    hole = [(LON + 0.001, LAT + 0.001), (LON + 0.002, LAT + 0.001), (LON + 0.002, 0.2)]
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(polygon_pm("Out", outer, [hole])), settings)
    assert code_of(e) == "outside_malaysia"


def test_extent_cap(tmp_path, settings):
    body = point_pm("A", (LON, LAT)) + point_pm("B", offset(LON, LAT, 16_000, 0))
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(body), settings)
    assert code_of(e) == "extent_too_large"
    site = parse(tmp_path, kml_doc(body), make_settings(tmp_path, max_extent_km=20.0))
    assert site.extent_km == pytest.approx(16.0, abs=0.05)


def test_too_many_features(tmp_path, settings):
    body = "".join(point_pm(f"P{i}", offset(LON, LAT, 10 * i, 0)) for i in range(51))
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(body), settings)
    assert code_of(e) == "too_many_features"
    body50 = "".join(point_pm(f"P{i}", offset(LON, LAT, 10 * i, 0)) for i in range(50))
    assert len(parse(tmp_path, kml_doc(body50), settings).features) == 50


@pytest.mark.parametrize("body", [
    "",
    "<Placemark><name>Nothing here</name></Placemark>",
    "<Placemark><Point><coordinates>  </coordinates></Point></Placemark>",
    "<NetworkLink><Link><href>http://example.com/x.kml</href></Link></NetworkLink>",
])
def test_no_geometry(tmp_path, settings, body):
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(body), settings)
    assert code_of(e) == "no_geometry"


# ---------------------------------------------------------------------------
# file type and size
# ---------------------------------------------------------------------------
def test_unsupported_extension(tmp_path, settings):
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(point_pm("P", SQUARE[0])), settings, name="site.txt")
    assert code_of(e) == "unsupported_type"


@pytest.mark.parametrize("content", [
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
    b"just some text, not xml",
    b"<html><body>hello</body></html>",
    b"",
])
def test_non_kml_content(tmp_path, settings, content):
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, content, settings)
    assert code_of(e) == "invalid_kml"


def test_kmz_extension_but_not_zip(tmp_path, settings):
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(point_pm("P", SQUARE[0])), settings, name="site.kmz")
    assert code_of(e) == "invalid_kmz"


def test_file_too_large(tmp_path):
    s = make_settings(tmp_path, max_upload_mb=0.001)
    body = "".join(point_pm(f"P{i}", offset(LON, LAT, i, 0)) for i in range(20))
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, kml_doc(body), s)
    assert code_of(e) == "file_too_large"


# ---------------------------------------------------------------------------
# KMZ
# ---------------------------------------------------------------------------
def test_kmz_doc_kml(tmp_path, settings):
    data = make_kmz({"doc.kml": kml_doc(polygon_pm("Zipped", SQUARE)), "files/icon.png": b"\x89PNG"})
    site = parse(tmp_path, data, settings, name="site.kmz")
    assert site.features[0].name == "Zipped"


def test_kmz_prefers_doc_kml(tmp_path, settings):
    data = make_kmz({"a_other.kml": kml_doc(point_pm("Other", SQUARE[0])),
                     "doc.kml": kml_doc(point_pm("Main", SQUARE[0]))})
    assert parse(tmp_path, data, settings, name="x.kmz").features[0].name == "Main"


def test_kmz_first_kml_when_no_doc(tmp_path, settings):
    data = make_kmz({"readme.txt": "hi", "sub/site.KML": kml_doc(point_pm("Sub", SQUARE[0]))})
    assert parse(tmp_path, data, settings, name="x.kmz").features[0].name == "Sub"


def test_kmz_saved_with_kml_extension(tmp_path, settings):
    data = make_kmz({"doc.kml": kml_doc(point_pm("Sniffed", SQUARE[0]))})
    assert parse(tmp_path, data, settings, name="renamed.kml").features[0].name == "Sniffed"


def test_kmz_without_kml(tmp_path, settings):
    data = make_kmz({"images/a.png": b"\x89PNG", "notes.txt": "no kml"})
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, data, settings, name="site.kmz")
    assert code_of(e) == "kmz_no_kml"


def test_kmz_zip_bomb_rejected_before_reading(tmp_path, monkeypatch):
    s = make_settings(tmp_path, max_kmz_uncompressed_mb=1.0)
    body = kml_doc(point_pm("P", SQUARE[0])).replace("<Document>", "<Document>" + " " * (3 * 1024 * 1024))
    data = make_kmz({"doc.kml": body})
    assert len(data) < 50_000                     # tiny on disk, 3 MB expanded

    def never(*a, **k):
        raise AssertionError("member must not be opened when its declared size exceeds the cap")
    monkeypatch.setattr(zipfile.ZipFile, "open", never)
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, data, s, name="bomb.kmz")
    assert code_of(e) == "kmz_too_large"


def _patch_uncompressed_size(data: bytes, new_size: int) -> bytes:
    """Make every header in a single-member zip under-declare the uncompressed size."""
    buf = bytearray(data)
    lh = buf.find(b"PK\x03\x04")
    struct.pack_into("<I", buf, lh + 22, new_size)
    cd = buf.find(b"PK\x01\x02")
    struct.pack_into("<I", buf, cd + 24, new_size)
    return bytes(buf)


def test_kmz_lying_header_does_not_bypass_cap(tmp_path):
    s = make_settings(tmp_path, max_kmz_uncompressed_mb=1.0)
    body = kml_doc(point_pm("P", SQUARE[0])).replace("<Document>", "<Document>" + " " * (3 * 1024 * 1024))
    data = _patch_uncompressed_size(make_kmz({"doc.kml": body}), 1000)
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, data, s, name="liar.kmz")
    assert code_of(e) in {"kmz_too_large", "invalid_kmz"}


def test_read_capped_enforces_hard_limit():
    assert _read_capped(io.BytesIO(b"a" * 100), 100) == b"a" * 100
    with pytest.raises(ScreeningError) as e:
        _read_capped(io.BytesIO(b"a" * 101), 100)
    assert e.value.code == "kmz_too_large"


def test_corrupt_kmz(tmp_path, settings):
    data = make_kmz({"doc.kml": kml_doc(point_pm("P", SQUARE[0]))})
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, data[:40], settings, name="broken.kmz")
    assert code_of(e) == "invalid_kmz"


# ---------------------------------------------------------------------------
# hostile XML
# ---------------------------------------------------------------------------
BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE kml [
 <!ENTITY lol "lol">
 <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
 <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
 <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
 <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
 <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
 <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
]>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>&lol9;</name>
<Point><coordinates>101.5,3.5</coordinates></Point></Placemark></Document></kml>
"""

XXE = """<?xml version="1.0"?>
<!DOCTYPE kml [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>&xxe;</name>
<Point><coordinates>101.5,3.5</coordinates></Point></Placemark></Document></kml>
"""

EXTERNAL_DTD = """<?xml version="1.0"?>
<!DOCTYPE kml SYSTEM "http://example.com/evil.dtd">
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
<Point><coordinates>101.5,3.5</coordinates></Point></Placemark></Document></kml>
"""


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, XXE, EXTERNAL_DTD],
                         ids=["billion_laughs", "xxe", "external_dtd"])
def test_unsafe_xml(tmp_path, settings, payload):
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, payload, settings)
    assert code_of(e) == "unsafe_xml"


def test_unsafe_xml_inside_kmz(tmp_path, settings):
    with pytest.raises(ScreeningError) as e:
        parse(tmp_path, make_kmz({"doc.kml": XXE}), settings, name="x.kmz")
    assert code_of(e) == "unsafe_xml"


# ---------------------------------------------------------------------------
# realistic fixtures
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name, kinds, area_ha", [
    ("flat_site_kedah.kml", ["polygon", "line", "point"], 42.2),
    ("hilly_site_pahang.kml", ["polygon"], 61.9),
    ("fpv_pond_perak.kml", ["polygon"], 26.7),
])
def test_fixtures_parse(settings, name, kinds, area_ha):
    from pyproj import Geod
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient

    site = validate_upload(FIXTURES / name, settings, name)
    assert [f.kind for f in site.features] == kinds
    area = abs(Geod(ellps="WGS84").geometry_area_perimeter(orient(Polygon(site.features[0].coords)))[0]) / 1e4
    assert area == pytest.approx(area_ha, abs=0.1)
