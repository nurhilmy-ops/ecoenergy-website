"""Safe KML/KMZ parsing and validation for uploaded site files.

Everything in an upload is untrusted: the XML is parsed with defusedxml (no DTDs,
entities or external references), KMZ members are size-checked before they are
read and read with a hard byte cap, and every coordinate is checked against the
Malaysia envelope. Nothing here fetches anything referenced by the file
(NetworkLinks, icons, overlays are ignored).

The shared input types (``ScreeningError``, ``Feature``, ``SiteInput``) live here
because this is the input layer every other engine module builds on; the package
``__init__`` re-exports them as the public API.
"""
from __future__ import annotations

import io
import math
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element, ParseError

import defusedxml
import defusedxml.ElementTree as DET
import shapely
from pyproj import Geod
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.polygon import orient

from ..config import Settings

GEOD = Geod(ellps="WGS84")

# Rough Malaysia envelope (Peninsular + Sabah/Sarawak + territorial waters).
MALAYSIA_LON = (99.0, 120.0)
MALAYSIA_LAT = (0.5, 8.0)

# KML namespaces we accept: OGC 2.2/2.3, the older Google Earth 2.0–2.2, or none.
KML_NAMESPACES = frozenset({
    "",
    "http://www.opengis.net/kml/2.2",
    "http://www.opengis.net/kml/2.3",
    "http://earth.google.com/kml/2.0",
    "http://earth.google.com/kml/2.1",
    "http://earth.google.com/kml/2.2",
})
ROOT_TAGS = frozenset({"kml", "Document", "Folder", "Placemark"})

NAME_MAX_CHARS = 80
# A 5 MB KML holds roughly this many vertices; the cap bounds geometry work for
# KMZs that expand to the 20 MB uncompressed limit.
MAX_TOTAL_VERTICES = 250_000
# Below this geodesic area a "polygon" is a sliver or a digitising slip.
MIN_POLYGON_AREA_M2 = 1.0

DEFAULT_NAMES = {"polygon": "Site", "line": "Route", "point": "Point"}

_COMMA_SPACES = re.compile(r"\s*,\s*")


class ScreeningError(Exception):
    """Message is safe to show to the visitor. `code` is a short machine key."""

    def __init__(self, message: str, code: str = "screening_error"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class Feature:
    name: str
    kind: str                                   # "polygon" | "line" | "point"
    coords: list[tuple[float, float]]           # (lon, lat); polygon = exterior ring, not closed
    holes: list[list[tuple[float, float]]] = field(default_factory=list)  # interior rings, not closed


@dataclass
class SiteInput:
    features: list[Feature]
    bbox: tuple[float, float, float, float]     # (min_lon, min_lat, max_lon, max_lat) of all features
    extent_km: float                            # max of bbox width/height in km
    source_filename: str
    # Names of polygons that self-intersected and were repaired with make_valid
    # (largest part kept). flags.py turns these into caveats.
    repaired: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------
def clean_text(value: str | None, max_chars: int = NAME_MAX_CHARS) -> str:
    """Strip control/format characters (incl. bidi overrides), collapse whitespace, cap length."""
    if not value:
        return ""
    kept = "".join(
        " " if ch in "\t\r\n" else ch
        for ch in value
        if ch in "\t\r\n" or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co", "Cn")
    )
    kept = " ".join(kept.split())
    if len(kept) > max_chars:
        kept = kept[: max_chars - 1].rstrip() + "…"
    return kept


def _split_tag(tag) -> tuple[str, str]:
    # Comments and processing instructions have non-string tags.
    if not isinstance(tag, str):
        return "#", ""
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return "", tag


def _is(el: Element, local: str) -> bool:
    ns, name = _split_tag(el.tag)
    return name == local and ns in KML_NAMESPACES


def _children(el: Element, local: str) -> list[Element]:
    return [c for c in el if _is(c, local)]


def _descendants(el: Element, local: str) -> list[Element]:
    return [c for c in el.iter() if c is not el and _is(c, local)]


# ---------------------------------------------------------------------------
# file handling
# ---------------------------------------------------------------------------
def _read_capped(stream, cap: int) -> bytes:
    """Read at most `cap` bytes; raise if the stream holds more (zip-bomb guard)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(1024 * 1024, cap + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > cap:
            raise ScreeningError(
                "The KML inside this KMZ is too large once uncompressed. "
                "Please upload a smaller file.", "kmz_too_large")
    return b"".join(chunks)


def _kml_from_kmz(data: bytes, settings: Settings) -> bytes:
    cap = settings.max_kmz_uncompressed_bytes
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            members = [i for i in zf.infolist()
                       if not i.is_dir() and i.filename.lower().endswith(".kml")]
            if not members:
                raise ScreeningError(
                    "This KMZ does not contain a .kml file. Please export the site from "
                    "Google Earth again, or upload the .kml directly.", "kmz_no_kml")
            # Google Earth writes the main document as doc.kml at the archive root.
            chosen = next((i for i in members if i.filename.lower() == "doc.kml"), members[0])
            if chosen.file_size > cap:
                raise ScreeningError(
                    "The KML inside this KMZ is too large once uncompressed. "
                    "Please upload a smaller file.", "kmz_too_large")
            with zf.open(chosen) as fh:
                # file_size can lie; the hard cap holds regardless of the header.
                return _read_capped(fh, cap)
    except ScreeningError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError,
            OSError, EOFError, ValueError) as exc:
        # RuntimeError: encrypted member; NotImplementedError: unsupported compression.
        raise ScreeningError(
            "This KMZ file could not be opened. It may be damaged or password-protected.",
            "invalid_kmz") from exc


def _parse_xml(data: bytes) -> Element:
    try:
        return DET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except defusedxml.DefusedXmlException as exc:
        raise ScreeningError(
            "This file contains XML features that are not allowed for security reasons "
            "(DTDs or entity declarations). Please export the site from Google Earth "
            "or your GIS software again.", "unsafe_xml") from exc
    except (ParseError, ValueError) as exc:
        raise ScreeningError(
            "This file is not valid KML. Please export the site from Google Earth "
            "or your GIS software as a .kml or .kmz file.", "invalid_kml") from exc


# ---------------------------------------------------------------------------
# geometry extraction
# ---------------------------------------------------------------------------
def _parse_coords(text: str | None) -> list[tuple[float, float]]:
    """KML <coordinates>: whitespace-separated "lon,lat[,alt]" tuples. Altitude is ignored
    (Google Earth writes it inconsistently). Tolerates spaces around commas."""
    if not text or not text.strip():
        return []
    pts: list[tuple[float, float]] = []
    for token in _COMMA_SPACES.sub(",", text.strip()).split():
        parts = [p for p in token.split(",") if p]
        if len(parts) < 2:
            raise ValueError(f"bad coordinate tuple {token[:40]!r}")
        lon, lat = float(parts[0]), float(parts[1])
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ValueError("non-finite coordinate")
        pts.append((lon, lat))
    return pts


def _dedupe(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop consecutive repeats and the closing vertex of a ring."""
    out: list[tuple[float, float]] = []
    for p in pts:
        if not out or p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _ring_coords(boundary: Element) -> list[list[tuple[float, float]]]:
    rings = []
    for ring in _descendants(boundary, "LinearRing"):
        for c in _children(ring, "coordinates"):
            rings.append(_parse_coords(c.text))
    return rings


def _geometries(el: Element):
    """Yield (kind, exterior, holes) for every supported geometry under `el`
    (recursing into MultiGeometry)."""
    for child in el:
        if _is(child, "Polygon"):
            outer = [r for b in _children(child, "outerBoundaryIs") for r in _ring_coords(b)]
            inner = [r for b in _children(child, "innerBoundaryIs") for r in _ring_coords(b)]
            if outer:
                yield "polygon", outer[0], inner
        elif _is(child, "LineString"):
            for c in _children(child, "coordinates"):
                yield "line", _parse_coords(c.text), []
        elif _is(child, "Point"):
            for c in _children(child, "coordinates"):
                yield "point", _parse_coords(c.text), []
        elif _is(child, "MultiGeometry"):
            yield from _geometries(child)


def _placemark_name(pm: Element) -> str:
    for n in _children(pm, "name"):
        return clean_text("".join(n.itertext()))
    return ""


def _distinct(pts) -> int:
    return len(set(pts))


def _build_polygon(name: str, ext, holes) -> tuple[Polygon, bool]:
    """Return a valid polygon and whether it needed repair."""
    if _distinct(ext) < 3:
        raise ScreeningError(
            f'The polygon "{name}" has fewer than three distinct corners. '
            "Please fix or remove it and upload again.", "invalid_polygon")
    holes = [h for h in holes if _distinct(h) >= 3]
    poly = Polygon(ext, holes)
    repaired = False
    if not poly.is_valid:
        fixed = shapely.make_valid(poly)
        parts = [g for g in getattr(fixed, "geoms", [fixed]) if isinstance(g, (Polygon, MultiPolygon))]
        polys = [p for g in parts for p in getattr(g, "geoms", [g]) if not p.is_empty]
        if not polys:
            raise ScreeningError(
                f'The polygon "{name}" has no area. Please fix or remove it and upload again.',
                "invalid_polygon")
        poly = max(polys, key=lambda p: p.area)
        repaired = True
    area, _ = GEOD.geometry_area_perimeter(orient(poly, 1.0))
    if not abs(area) > MIN_POLYGON_AREA_M2:
        raise ScreeningError(
            f'The polygon "{name}" has no area. Please fix or remove it and upload again.',
            "invalid_polygon")
    return poly, repaired


def _check_envelope(name: str, rings) -> None:
    for ring in rings:
        for lon, lat in ring:
            if not (MALAYSIA_LON[0] <= lon <= MALAYSIA_LON[1]
                    and MALAYSIA_LAT[0] <= lat <= MALAYSIA_LAT[1]):
                hint = ""
                if (MALAYSIA_LON[0] <= lat <= MALAYSIA_LON[1]
                        and MALAYSIA_LAT[0] <= lon <= MALAYSIA_LAT[1]):
                    hint = " The coordinates look swapped (latitude written before longitude)."
                raise ScreeningError(
                    f'"{name}" lies outside Malaysia. This tool screens sites in Malaysia '
                    f"only (longitude 99–120°E, latitude 0.5–8°N).{hint}", "outside_malaysia")


def extract_features(root: Element, settings: Settings) -> tuple[list[Feature], list[str]]:
    ns, local = _split_tag(root.tag)
    if ns not in KML_NAMESPACES or local not in ROOT_TAGS:
        raise ScreeningError(
            "This file is not a KML document. Please export the site from Google Earth "
            "or your GIS software as a .kml or .kmz file.", "invalid_kml")

    placemarks = [root] if _is(root, "Placemark") else _descendants(root, "Placemark")
    features: list[Feature] = []
    repaired: list[str] = []
    counters = {"polygon": 0, "line": 0, "point": 0}
    vertices = 0
    for pm in placemarks:
        base = _placemark_name(pm)
        try:
            geoms = list(_geometries(pm))
        except ValueError as exc:
            label = f' in "{base}"' if base else ""
            raise ScreeningError(
                f"Some coordinates{label} could not be read. Please export the site from "
                "Google Earth or your GIS software again.", "invalid_coordinates") from exc
        kinds_here = [g[0] for g in geoms]
        part_no = {"polygon": 0, "line": 0, "point": 0}
        for kind, ext, holes in geoms:
            ext = _dedupe(ext) if kind == "polygon" else [p for i, p in enumerate(ext)
                                                          if i == 0 or p != ext[i - 1]]
            holes = [_dedupe(h) for h in holes]
            if not ext:
                continue
            counters[kind] += 1
            part_no[kind] += 1
            name = base or f"{DEFAULT_NAMES[kind]} {counters[kind]}"
            if base and kinds_here.count(kind) > 1:
                name = clean_text(f"{base} (part {part_no[kind]})")

            vertices += len(ext) + sum(len(h) for h in holes)
            if vertices > MAX_TOTAL_VERTICES:
                raise ScreeningError(
                    "This file has too many vertices to screen. Please simplify the "
                    "boundaries and upload again.", "too_complex")

            # Check every supplied coordinate, before any repair discards parts.
            _check_envelope(name, [ext, *holes])
            if kind == "point":
                ext = ext[:1]
            elif kind == "line" and _distinct(ext) < 2:
                raise ScreeningError(
                    f'The line "{name}" has fewer than two distinct points. '
                    "Please fix or remove it and upload again.", "invalid_line")
            elif kind == "polygon":
                poly, was_repaired = _build_polygon(name, ext, holes)
                if was_repaired:
                    repaired.append(name)
                ext = list(poly.exterior.coords)[:-1]
                holes = [list(r.coords)[:-1] for r in poly.interiors]

            feat = Feature(name=name, kind=kind, coords=[(float(x), float(y)) for x, y in ext],
                           holes=[[(float(x), float(y)) for x, y in h] for h in holes])
            features.append(feat)
            if len(features) > settings.max_features:
                raise ScreeningError(
                    f"This file has more than {settings.max_features} features "
                    "(polygons, lines and points). Please upload only the site boundary "
                    "and key routes or points.", "too_many_features")
    return features, repaired


def _extent_km(bbox: tuple[float, float, float, float]) -> float:
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2
    mid_lon = (min_lon + max_lon) / 2
    _, _, width = GEOD.inv(min_lon, mid_lat, max_lon, mid_lat)
    _, _, height = GEOD.inv(mid_lon, min_lat, mid_lon, max_lat)
    return max(abs(width), abs(height)) / 1000.0


def feature_geometry(f: Feature):
    """Shapely geometry (lon/lat) for a feature."""
    if f.kind == "polygon":
        return Polygon(f.coords, f.holes)
    if f.kind == "line":
        return LineString(f.coords)
    return shapely.Point(f.coords[0])


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def validate_upload(path: Path, settings: Settings, original_filename: str) -> SiteInput:
    """Parse and validate an uploaded .kml/.kmz. Raises ScreeningError for: unsupported type,
    file too large, unsafe XML (entities/DTD), KMZ without a .kml or exceeding the uncompressed cap,
    no usable geometry, more than settings.max_features features, any coordinate outside the
    Malaysia envelope (lon 99.0–120.0, lat 0.5–8.0), or extent > settings.max_extent_km.

    The type is chosen by extension (.kml/.kmz) but the content is sniffed, so a KMZ
    saved with a .kml name (or vice versa) still works.
    """
    path = Path(path)
    filename = clean_text(original_filename or path.name, 200)
    ext = Path(original_filename or path.name).suffix.lower()
    if ext not in (".kml", ".kmz"):
        raise ScreeningError(
            "Please upload a .kml or .kmz file (exported from Google Earth or GIS software).",
            "unsupported_type")
    limit = settings.max_upload_bytes
    try:
        if path.stat().st_size > limit:
            raise ScreeningError(
                f"This file is larger than the {settings.max_upload_mb:g} MB limit.",
                "file_too_large")
        with path.open("rb") as fh:
            data = fh.read(limit + 1)
    except OSError as exc:
        raise ScreeningError("The uploaded file could not be read. Please try again.",
                             "unreadable_file") from exc
    if len(data) > limit:
        raise ScreeningError(f"This file is larger than the {settings.max_upload_mb:g} MB limit.",
                             "file_too_large")

    if data[:4] == b"PK\x03\x04":
        data = _kml_from_kmz(data, settings)
    elif ext == ".kmz":
        raise ScreeningError(
            "This KMZ file could not be opened. It may be damaged or password-protected.",
            "invalid_kmz")

    root = _parse_xml(data)
    features, repaired = extract_features(root, settings)
    if not features:
        raise ScreeningError(
            "No site geometry was found in this file. It needs at least one polygon, "
            "line or point (placemark).", "no_geometry")

    lons = [x for f in features for ring in [f.coords, *f.holes] for x, _ in ring]
    lats = [y for f in features for ring in [f.coords, *f.holes] for _, y in ring]
    bbox = (min(lons), min(lats), max(lons), max(lats))
    extent = _extent_km(bbox)
    if extent > settings.max_extent_km:
        raise ScreeningError(
            f"The features in this file span about {extent:.1f} km, more than the "
            f"{settings.max_extent_km:g} km limit for one screening. Please upload one site "
            "(or one cluster of nearby sites) at a time.", "extent_too_large")
    return SiteInput(features=features, bbox=bbox, extent_km=extent,
                     source_filename=filename, repaired=repaired)
