"""Rule-based flags, follow-ups, caveats and figure captions.

ALL wording that reaches the visitor's report lives in this module. Every rule reads
the computed numbers in the result dict (never KML text) and every threshold is a
named constant below with the basis for it, so thresholds and wording can be refined
(e.g. after legal review) without touching the analysis.

Site and route names are inserted only as quoted labels; they never select a rule.
"""
from __future__ import annotations

import math

from .analysis import SMALL_SITE_MIN_CELLS

# ---------------------------------------------------------------------------
# thresholds
# ---------------------------------------------------------------------------
# A site is flagged for a KPKT class when more than this share of its area falls in it.
# Basis: screening tolerance — at 30 m one or two noisy DEM cells (canopy edges, drains)
# should not trigger a hill-land flag on an otherwise flat site.
KPKT_FLAG_MIN_PCT = 0.5

# Ground-mounted PV: flag when more than STEEP_PV_AREA_PCT of a site is steeper than
# STEEP_PV_SLOPE_DEG. Basis: screening heuristic only — ground-mount layouts on slopes
# above roughly 10° commonly need grading or terracing; racking tolerances are
# product-specific and must come from the supplier.
STEEP_PV_SLOPE_DEG = 10.0
STEEP_PV_AREA_PCT = 10.0
STEEP_BINS = ("10-15", "15-25", "25-35", ">35")      # slope bins above STEEP_PV_SLOPE_DEG

# Relief (max - min elevation) within one site above which earthworks balance and
# stormwater design become material cost items. Basis: screening heuristic; design
# itself follows MSMA 2nd Edition (DID 2012).
HIGH_RELIEF_M = 30.0

# PROVISIONAL — pending legal research on hill/highland development guidelines
# (definitions differ between guidelines and states). Conservative screening trigger
# only; see elevated_terrain_flag() for the deliberately cautious wording.
ELEVATED_TERRAIN_M = 150.0

# Floating PV: a water surface should be flat on the DEM. Relief above this, or a
# 90th-percentile slope above FPV_LAND_SLOPE_P90_DEG, means land/bunds/islands inside
# the polygon or a pond newer than the DEM. Basis: DEM noise over open water is
# typically a few metres at most; values above these are unlikely to be water.
FPV_LAND_RELIEF_M = 5.0
FPV_LAND_SLOPE_P90_DEG = 5.0

# Share of the analysed frame without DEM values above which statistics are flagged.
# Basis: a few percent of gaps (sea, voids) does not change site statistics materially.
DEM_NODATA_PCT = 5.0

# Route gradient window, quoted in the route_grade wording (the analysis uses >= 90 m).
ROUTE_GRADE_WINDOW_M = 90

# ---------------------------------------------------------------------------
# sources quoted in flags (kept here so citations can be corrected in one place)
# ---------------------------------------------------------------------------
SRC_KPKT = ("KPKT hill-land development guidelines "
            "(Garis Panduan Perancangan Pembangunan di Kawasan Bukit dan Tanah Tinggi)")
SRC_MSMA = "Urban Stormwater Management Manual for Malaysia (MSMA), 2nd Edition (DID 2012)"
SRC_EIA = ("Environmental Quality (Prescribed Activities) (Environmental Impact Assessment) "
           "Order 2015, under the Environmental Quality Act 1974")
SRC_SURVEY = "Licensed Land Surveyors Act 1958"

LEVEL_ORDER = {"warning": 0, "caution": 1, "info": 2}

STAMP_TEMPLATE = "Desktop screening — not a survey · DEM: {name} ({epoch}) · EcoEnergy Consultancy"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _ok(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _q(name: str) -> str:
    return f"“{name}”"


def _fmt(x, nd: int = 1) -> str:
    return f"{x:,.{nd}f}" if _ok(x) else "n/a"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return "; ".join(items[:-1]) + "; " + items[-1]


def _flag(level: str, code: str, title: str, detail: str, source: str | None = None) -> dict:
    return {"level": level, "code": code, "title": title, "detail": detail, "source": source}


def figure_stamp(dem: dict) -> str:
    """Footer stamp printed on every figure."""
    # "2011–2015 (TanDEM-X acquisitions)" -> "2011–2015, TanDEM-X acquisitions" so the
    # stamp does not end up with nested brackets.
    epoch = str(dem.get("epoch", "unknown"))
    if epoch.endswith(")") and " (" in epoch:
        epoch = epoch[:-1].replace(" (", ", ", 1)
    return STAMP_TEMPLATE.format(name=dem.get("name", "unknown"), epoch=epoch)


# ---------------------------------------------------------------------------
# individual rules
# ---------------------------------------------------------------------------
_KPKT_RULES = {
    "II": ("caution", "kpkt_class_ii", "15–25°",
           "Slopes of 15–25° (KPKT Class II) inside the site",
           "Under the KPKT hill-land guidelines, Class II ground is generally developable "
           "only with engineering controls such as slope protection and erosion and sediment "
           "control; expect the local authority to ask for them."),
    "III": ("warning", "kpkt_class_iii", "25–35°",
            "Slopes of 25–35° (KPKT Class III) inside the site",
            "Class III ground is restricted under the KPKT hill-land guidelines: development "
            "typically needs a geotechnical report and may not be approved. Treat these areas "
            "as unusable for layout until a survey and geotechnical assessment say otherwise."),
    "IV": ("warning", "kpkt_class_iv", "35° or steeper",
           "Slopes of 35° or more (KPKT Class IV) inside the site",
           "Class IV ground is generally not permitted for development under the KPKT "
           "hill-land guidelines. Exclude these areas from any usable-area or capacity estimate."),
}


def kpkt_flags(sites: list[dict]) -> list[dict]:
    out = []
    for cls, (level, code, band, title, consequence) in _KPKT_RULES.items():
        hits = [f"{_q(s['name'])}: {_fmt(s['kpkt_pct'][cls])}% of its area"
                for s in sites if _ok(s["kpkt_pct"].get(cls)) and s["kpkt_pct"][cls] > KPKT_FLAG_MIN_PCT]
        if hits:
            out.append(_flag(level, code, title,
                             f"Share of site area at {band} on the DEM — {_join(hits)}. {consequence}",
                             SRC_KPKT))
    return out


def all_class_i_flag(sites: list[dict]) -> dict | None:
    measured = [s for s in sites if all(_ok(s["kpkt_pct"].get(c)) for c in ("II", "III", "IV"))]
    if not measured or any(s["kpkt_pct"][c] > KPKT_FLAG_MIN_PCT
                           for s in measured for c in ("II", "III", "IV")):
        return None
    return _flag(
        "info", "all_class_i", "Site area screens as KPKT Class I (below 15°)",
        f"No site has more than {KPKT_FLAG_MIN_PCT:g}% of its area at 15° or steeper on this DEM, "
        "so the land screens as Class I, which the KPKT hill-land guidelines generally treat as "
        "developable. A 30 m elevation model smooths out short steep features such as bund "
        "faces, drain banks and cuttings, so a survey can still find locally steeper ground.",
        SRC_KPKT)


def steep_for_ground_pv_flag(sites: list[dict]) -> dict | None:
    hits = []
    for s in sites:
        vals = [s["slope_bins_pct"].get(b) for b in STEEP_BINS]
        if all(_ok(v) for v in vals) and sum(vals) > STEEP_PV_AREA_PCT:
            hits.append(f"{_q(s['name'])}: {_fmt(sum(vals))}%")
    if not hits:
        return None
    return _flag(
        "caution", "steep_for_ground_pv",
        f"More than {STEEP_PV_AREA_PCT:g}% of site area is steeper than {STEEP_PV_SLOPE_DEG:g}°",
        f"Share of site area steeper than {STEEP_PV_SLOPE_DEG:g}° — {_join(hits)}. Ground this "
        "steep typically needs grading or terracing for ground-mounted PV, which adds earthworks "
        "cost and erosion-control obligations. Confirm the racking supplier's slope tolerance "
        "for the chosen mounting structure before fixing the layout.")


def high_relief_flag(sites: list[dict]) -> dict | None:
    hits = [f"{_q(s['name'])}: {_fmt(s['relief_m'], 0)} m" for s in sites
            if _ok(s.get("relief_m")) and s["relief_m"] > HIGH_RELIEF_M]
    if not hits:
        return None
    return _flag(
        "info", "high_relief", f"More than {HIGH_RELIEF_M:g} m of elevation change within a site",
        f"Elevation range (highest minus lowest point) — {_join(hits)}. Plan for an earthworks "
        "balance and for stormwater and erosion control designed to MSMA 2nd Edition (DID 2012) "
        "at design stage, and allow for them in early cost estimates.",
        SRC_MSMA)


def elevated_terrain_flag(sites: list[dict]) -> dict | None:
    # Wording kept deliberately non-committal pending legal research (see ELEVATED_TERRAIN_M).
    hits = [f"{_q(s['name'])}: up to {_fmt(s['elev_max_m'], 0)} m" for s in sites
            if _ok(s.get("elev_max_m")) and s["elev_max_m"] >= ELEVATED_TERRAIN_M]
    if not hits:
        return None
    return _flag(
        "caution", "elevated_terrain", "Elevated terrain — hill or highland guidelines may apply",
        f"Highest DEM elevation — {_join(hits)} (surface model: includes tree canopy). Depending "
        "on the state and the local plan, hill or highland development guidelines may apply to "
        "land at this elevation. Check with the local planning authority (PBT) before "
        "committing to the site.",
        None)


def fpv_flags(sites: list[dict], dem: dict) -> list[dict]:
    out = [_flag(
        "info", "fpv_dem_epoch", "The elevation model cannot see the pond bed",
        f"The {dem['name']} was acquired in {dem['epoch']}. Ponds excavated or flooded after "
        "that do not appear in it, and where water was present it records the water surface, "
        "not the bed, so the slope and KPKT figures for a pond describe its water surface "
        "only. For floating solar, a bathymetric survey, seasonal water-level records and "
        "the condition of the bunds govern the design — no elevation model provides them.")]
    hits = []
    for s in sites:
        relief, p90 = s.get("relief_m"), s.get("slope_p90_deg")
        if (_ok(relief) and relief > FPV_LAND_RELIEF_M) or (_ok(p90) and p90 > FPV_LAND_SLOPE_P90_DEG):
            hits.append(f"{_q(s['name'])}: {_fmt(relief)} m relief, 90th-percentile slope "
                        f"{_fmt(p90)}°")
    if hits:
        out.append(_flag(
            "caution", "fpv_land_inside", "Land or uneven ground inside a floating-solar site",
            f"A water surface should be flat on the elevation model, but {_join(hits)}. Either "
            f"the pond post-dates the DEM ({dem['epoch']}) or the polygon includes land such as "
            "bunds, banks or islands. Check the boundary against current satellite imagery "
            "before estimating water area or capacity."))
    return out


def small_site_flag(sites: list[dict]) -> dict | None:
    hits = [f"{_q(s['name'])} ({s['cells']} cells)" for s in sites
            if s.get("cells", 0) < SMALL_SITE_MIN_CELLS]
    if not hits:
        return None
    return _flag(
        "info", "small_site", "Site smaller than the elevation grid can resolve",
        f"Fewer than {SMALL_SITE_MIN_CELLS} DEM cells fall inside {_join(hits)}. Its statistics "
        "are interpolated from neighbouring cells and are indicative only.")


def dem_nodata_flag(dem: dict) -> dict | None:
    pct = dem.get("nodata_pct")
    if not (_ok(pct) and pct > DEM_NODATA_PCT):
        return None
    return _flag(
        "caution", "dem_nodata", "Gaps in the elevation data",
        f"{_fmt(pct)}% of the analysed area has no elevation value (open sea or data voids). "
        "Statistics use the remaining cells only; check that the boundary is on land.")


def route_grade_flag(routes: list[dict]) -> dict | None:
    if not routes:
        return None
    rows = [f"{_q(r['name'])}: max grade {_fmt(r['max_grade_pct'])}% over {_fmt(r['length_km'], 2)} km "
            f"(total climb {_fmt(r['total_ascent_m'], 0)} m)" for r in routes]
    return _flag(
        "info", "route_grade", "Route gradients",
        f"Steepest gradient along each route, measured over at least {ROUTE_GRADE_WINDOW_M} m — "
        f"{_join(rows)}. Short pitches at drains, embankments and road crossings can be steeper "
        "than a 30 m DEM shows.")


def eia_check_flag(totals: dict) -> dict | None:
    area = totals.get("total_area_ha")
    if not (_ok(area) and area > 0):
        return None
    return _flag(
        "info", "eia_check", "Check EIA requirements for the total area",
        f"Total polygon area is {_fmt(area, 2)} ha. Whether an Environmental Impact Assessment "
        "is required depends on the activity and area categories in the schedules of the "
        "Environmental Quality (Prescribed Activities) (Environmental Impact Assessment) Order "
        "2015, and on factors such as hill land, forest clearing or conversion of agricultural "
        "land. Have a qualified EIA consultant check the site against the current schedules.",
        SRC_EIA)


# ---------------------------------------------------------------------------
# public builders
# ---------------------------------------------------------------------------
def build_flags(result: dict) -> list[dict]:
    """Flags for a result dict (needs meta, dem, totals, sites, routes), most severe first."""
    sites, routes = result.get("sites", []), result.get("routes", [])
    dem, totals = result["dem"], result["totals"]
    scheme = (result.get("meta") or {}).get("scheme")
    candidates: list[dict | None] = [
        *kpkt_flags(sites),
        all_class_i_flag(sites) if scheme != "fpv" else None,   # meaningless over water
        steep_for_ground_pv_flag(sites) if scheme != "fpv" else None,
        high_relief_flag(sites),
        elevated_terrain_flag(sites),
        *(fpv_flags(sites, dem) if scheme == "fpv" else []),
        small_site_flag(sites),
        dem_nodata_flag(dem),
        route_grade_flag(routes),
        eia_check_flag(totals),
    ]
    flags = [f for f in candidates if f]
    return sorted(flags, key=lambda f: LEVEL_ORDER[f["level"]])   # stable within a level


def build_followups(result: dict) -> list[dict]:
    scheme = (result.get("meta") or {}).get("scheme")
    sites = result.get("sites", [])
    out = [
        {"title": "Licensed topographic survey",
         "detail": "Before layout, earthworks or drainage design, commission a topographic survey "
                   "by a licensed land surveyor (Licensed Land Surveyors Act 1958), or LiDAR / "
                   "drone photogrammetry tied to surveyed ground control points."},
        {"title": "Geological map review (JMG)",
         "detail": "Review the Jabatan Mineral dan Geosains (JMG) geological map sheet for the "
                   "site: formation, lithology and any karst or ex-mining ground that affects "
                   "piling, anchoring or foundations."},
        {"title": "Rainfall and climate data (MET Malaysia)",
         "detail": "Obtain climate normals and rainfall records from the nearest MET Malaysia "
                   "station; rainfall intensity feeds stormwater design to MSMA 2nd Edition."},
        {"title": "Surrounding land-use scan (1 / 5 / 10 km)",
         "detail": "Map settlements, schools, rivers and water intakes, forest reserves, industry "
                   "and mining within 1 km, 5 km and 10 km of the site as context for EIA and "
                   "SIA scoping."},
        {"title": "Land title, zoning and local authority requirements",
         "detail": "Confirm the land title, category of land use and any express conditions, the "
                   "zoning in the local plan (Rancangan Tempatan), and the requirements of the "
                   "local authority (PBT) for this type of development."},
    ]
    steep = any(_ok(s["kpkt_pct"].get(c)) and s["kpkt_pct"][c] > KPKT_FLAG_MIN_PCT
                for s in sites for c in ("III", "IV"))
    if steep:
        out.append({"title": "Geotechnical slope assessment",
                    "detail": "Slopes of 25° or more were found inside the site. Commission a "
                              "geotechnical assessment of slope stability before any layout "
                              "or earthworks decision."})
    if result.get("routes"):
        out.append({"title": "Route wayleave and crossings",
                    "detail": "Confirm land access and wayleaves along the cable or access route "
                              "and identify road, river and railway crossings and TNB technical "
                              "requirements; none of these show on an elevation model."})
    if scheme == "fpv":
        out += [
            {"title": "Bathymetric survey",
             "detail": "Survey water depth across the pond to design anchoring and mooring and "
                       "to confirm the usable water area."},
            {"title": "Seasonal water-level records",
             "detail": "Obtain or start recording water levels through wet and dry seasons; the "
                       "drawdown range sets mooring load cases and the risk of panels grounding."},
            {"title": "Bund geotechnical assessment",
             "detail": "Have the bunds and embankments assessed by a geotechnical engineer, "
                       "especially for ex-mining ponds, including the consequence of a bund failure."},
        ]
    return out


def build_caveats(result: dict, repaired: list[str] | None = None) -> list[str]:
    dem = result["dem"]
    model = str(dem.get("model_type", ""))
    out = [
        "Screening grade only: this is a desktop terrain screening from an open global "
        "elevation model, not a survey.",
    ]
    if "DSM" in model or "surface" in model.lower():
        out.append(
            f"The {dem['name']} is a surface model: it records the top of tree canopy and "
            "buildings, not bare ground. Plantations, forest and built-up areas read higher than "
            "the ground beneath them, and slopes at their edges can be exaggerated.")
    else:
        out.append(f"Elevation model type: {model}. Check whether it represents bare ground or "
                   "the top of vegetation and buildings before relying on it.")
    out += [
        f"Elevations show the ground as it was in {dem['epoch']}. Ponds, cuttings, platforms and "
        "buildings made since then are not represented.",
        f"The nominal {dem['nominal_resolution_m']} m resolution (analysed at about "
        f"{_fmt(dem.get('grid_spacing_m'), 0)} m) smooths out bunds, drains and short steep "
        "cuttings, so local slopes are underestimated.",
        "Site geometry is used exactly as supplied in the uploaded KML/KMZ file; it has not "
        "been checked against title plans or survey boundaries.",
        "Not for authority submissions or design: planning applications, earthworks, drainage "
        "and structural design need a licensed survey and qualified engineers.",
    ]
    for name in repaired or []:
        out.append(f"The boundary of {_q(name)} crossed itself and was repaired automatically "
                   "(the largest valid part was kept); check it against the intended boundary.")
    return out


def figure_entries(result: dict) -> list[dict]:
    dem = result["dem"]
    sites, routes = result.get("sites", []), result.get("routes", [])
    class_i = (result.get("kpkt_overall_pct") or {}).get("I")
    epsg = result["location"]["utm_epsg"]
    biggest = max(sites, key=lambda s: s["area_ha"] or 0)["name"] if sites else None
    through = f"through {_q(biggest)}" if biggest else "through the centre of the features"
    shown = min(len(routes), 4)
    route_part = (f", plus the elevation profile along {shown} route{'s' if shown != 1 else ''}"
                  if routes else "")
    class_part = (f"; {_fmt(class_i)}% of the site area is KPKT Class I (below 15°)"
                  if _ok(class_i) else "")
    return [
        {"file": "1_site_layout.png", "title": "Site layout",
         "caption": "Site boundaries, routes and points as supplied in the KML, with areas in "
                    f"hectares, on a local UTM grid ({epsg})."},
        {"file": "2_elevation.png", "title": "Elevation and contours",
         "caption": f"Shaded {dem['name']} surface elevation with contours every "
                    f"{_fmt(result.get('contour_interval_m'), 0)} m; tree canopy and buildings "
                    "are included in the surface."},
        {"file": "3_slope_classes.png", "title": "Slope classes",
         "caption": "Slope from the elevation model in seven bands, with the KPKT class "
                    f"boundaries at 15°, 25° and 35°{class_part}."},
        {"file": "4_profiles.png", "title": "Terrain profiles",
         "caption": f"West–east and south–north sections {through}{route_part}; the vertical "
                    "scale is exaggerated and not to scale."},
    ]
