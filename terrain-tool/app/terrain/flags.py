"""Rule-based flags, follow-ups, caveats and figure captions.

ALL wording that reaches the visitor's report lives in this module. Every rule reads
the computed numbers in the result dict (never KML text) and every threshold is a
named constant below with the instrument it comes from, so thresholds and wording can
be refined (e.g. after legal review) without touching the analysis. Each flag carries
the instrument it relies on in its "source" field.

The tool classifies ground by SLOPE ONLY. The KPKT hill-land classes also depend on
geotechnical condition, so every class statement says "slope-based indication".

Site and route names are inserted only as quoted labels; they never select a rule.
The state (from the DOSM boundary lookup) selects the state-specific rules.
"""
from __future__ import annotations

import math

from .analysis import SLOPE_BINS, SMALL_SITE_MIN_CELLS
from .dem import COPERNICUS_STAMP_CREDIT

# ---------------------------------------------------------------------------
# thresholds
# ---------------------------------------------------------------------------
# A site counts for a slope class or slope item when more than this share of its area
# falls in it. Basis: screening tolerance (ours, not from any instrument) — at 30 m one
# or two noisy DEM cells (canopy edges, drains) should not trigger a flag on an
# otherwise flat site.
KPKT_FLAG_MIN_PCT = 0.5

# PLANMalaysia (then JPBD Semenanjung Malaysia, KPKT), "Garis Panduan Perancangan
# Pembangunan di Kawasan Bukit dan Tanah Tinggi" (2009), Jadual 1 slope classes:
# I < 15°, II 15° to < 25°, III 25° to < 35°, IV >= 35° (see analysis.KPKT_EDGES_DEG).
KPKT_CLASS_II_MIN_DEG = 15.0
# Same guideline, Jadual 1: on mixed sites where Class IV is small (< 10%) the developer
# must apply for an exemption, which may be granted with stricter engineering works.
KPKT_CLASS_IV_EXEMPTION_PCT = 10.0
# Same guideline, s.2 land categories by elevation above sea level: Tanah Rendah < 150 m,
# Tanah Bukit 150–300 m, Tanah Tinggi > 300 m to < 1,000 m, Gunung > 1,000 m. Applied to
# each site's highest DEM elevation.
TANAH_BUKIT_MIN_M = 150.0
TANAH_TINGGI_MIN_M = 300.0
GUNUNG_MIN_M = 1000.0

# Environmental Quality (Prescribed Activities) (Environmental Impact Assessment) Order
# 2015, P.U. (A) 195/2015. Item 13 (development in slope area): ground at >= 25° and
# < 35°; less than 50% of the area -> First Schedule 13, 50% or more -> Second Schedule
# 13(a). Second Schedule 13(b): road, tunnel or bridge traversing slope >= 35°.
EIA_SLOPE_MIN_DEG = 25.0
EIA_SLOPE_MAX_DEG = 35.0
EIA_SLOPE_SECOND_SCHEDULE_PCT = 50.0
EIA_ROUTE_SLOPE_DEG = 35.0
EIA_ROUTE_GRADE_PCT = 100.0 * math.tan(math.radians(EIA_ROUTE_SLOPE_DEG))   # 70.0 %
# Same Order, area-based items that may apply depending on the land (hectares):
# First Schedule 5(a) / Second Schedule 5(a): conversion of forest at >= 300 m above
# mean sea level to other land use, 20 ha to < 100 ha / 100 ha or more.
EIA_FOREST_ELEVATION_M = 300.0
EIA_FOREST_300M_FIRST_HA = 20.0
EIA_FOREST_300M_SECOND_HA = 100.0
# First Schedule 5(d) / Second Schedule 5(f): conversion of mangrove, peat swamp or
# freshwater swamp forest, 20 ha to < 50 ha / 50 ha or more.
EIA_SWAMP_FOREST_FIRST_HA = 20.0
EIA_SWAMP_FOREST_SECOND_HA = 50.0
# Second Schedule 3(b): drainage of wetland, wildlife habitat or dry inland forest >= 20 ha.
EIA_WETLAND_DRAINAGE_HA = 20.0
# First Schedule 17: development of industrial estate >= 20 ha.
EIA_INDUSTRIAL_ESTATE_HA = 20.0
# Same Order, paragraph 4: in Sabah and Sarawak it applies only to a limited set of
# items; items 5, 13, First Schedule 17 and Second Schedule 3 are not among them.
EIA_LIMITED_SCOPE_STATES = ("Sabah", "Sarawak")

# Street, Drainage and Building Act 1974 (Act 133) s.70(2)(c), inserted by Act A1588
# (2019): geotechnical report verified by an Accredited Checker for "erection involving
# slope with a gradient more than twenty-five degrees and total vertical height more
# than ten metres". Site relief stands in for slope height at screening level.
SDBA_SLOPE_DEG = 25.0
SDBA_HEIGHT_M = 10.0

# Penang: news reports (New Straits Times, RTM, 10 Dec 2025) on the Penang Structure Plan
# 2030 (RSNPP 2030, gazetted 24 Oct 2019): no development on hill land above 76 m
# (250 ft) or on slopes steeper than 25°; under review in the draft RSNPP 2040.
PENANG_STATE = "Pulau Pinang"          # DOSM spelling
PENANG_HILL_M = 76.0
PENANG_SLOPE_DEG = 25.0

# Pahang: PLANMalaysia@Pahang, Garis Panduan Perancangan Pembangunan Tenaga Solar Negeri
# Pahang (GPP PHG 03, 2022): terrain steeper than 10 degrees is not suitable for solar
# farms. Kaedah-Kaedah Kawalan Perancangan (Pemajuan Tanah Bukit, Tanah Tinggi dan Lereng
# Bukit)(Pahang) 2019: urban development on highland >= 300 m or slopes >= 25° goes to
# the state KSAS Technical Committee (JTKSAS).
PAHANG_STATE = "Pahang"
PAHANG_SOLAR_MAX_DEG = 10.0
PAHANG_JTKSAS_ELEV_M = 300.0
PAHANG_JTKSAS_SLOPE_DEG = 25.0

# Ground-mounted PV slope context (no instrument sets a limit). Grades quoted from
# vendor datasheets and NREL: 15% = single-axis tracker standard N–S tolerance (Array
# Technologies DuraTrack HZ v3, TrinaTracker Vanguard 1P); 10% = standard conditions of
# one fixed-tilt structure (TrinaTracker FixOrigin) and NREL/TP-6A20-91900 (2024)
# Reference-scenario exclusion. IFC (2015) s.6.3.4 gives no numeric limit.
PV_GRADE_TRACKER_PCT = 15.0
PV_GRADE_FIXED_PCT = 10.0
PV_SLOPE_TRACKER_DEG = math.degrees(math.atan(PV_GRADE_TRACKER_PCT / 100.0))   # ≈ 8.5°
PV_SLOPE_FIXED_DEG = math.degrees(math.atan(PV_GRADE_FIXED_PCT / 100.0))       # ≈ 5.7°
# Share of a site above those slopes that raises the flag. Basis: screening heuristic
# (ours) — a tenth of a site is enough to change layout and earthworks.
STEEP_PV_AREA_PCT = 10.0
PV_FLAG_EXEMPT_SCHEMES = ("fpv", "rooftop")

# Gross indicative capacity: IFC (2015) Utility-Scale Solar PV Power Plants, Table 7,
# crystalline-silicon ground mount in Thailand and Indonesia: about 0.8–1.2 ha/MWp
# ("exact area will vary according to the tilt angles and pitch").
HA_PER_MWP_LOW = 0.8
HA_PER_MWP_HIGH = 1.2
CAPACITY_MIN_AREA_HA = 1.0
CAPACITY_SCHEMES = ("lss", "cress", "other", None)

# Relief (max - min elevation) within one site above which earthworks balance and
# stormwater design become material cost items. Basis: screening heuristic; design
# itself follows MSMA 2nd Edition (DID/JPS 2012).
HIGH_RELIEF_M = 30.0

# Floating PV: a water surface should be flat on the DEM. Relief above this, or a
# 90th-percentile slope above FPV_LAND_SLOPE_P90_DEG, means land/bunds/islands inside
# the polygon or a pond newer than the DEM. Basis: DEM noise over open water is
# typically a few metres at most; values above these are unlikely to be water.
FPV_LAND_RELIEF_M = 5.0
FPV_LAND_SLOPE_P90_DEG = 5.0

# Share of the analysed frame without DEM values above which statistics are flagged.
# Basis: a few percent of gaps (sea, voids) does not change site statistics materially.
DEM_NODATA_PCT = 5.0

# Route gradient window, quoted in the route wording (the analysis uses >= 90 m).
ROUTE_GRADE_WINDOW_M = 90

# Contour floor quoted in the caveats (Settings.contour_min_interval_m default). Basis:
# ASPRS Positional Accuracy Standards (2014; repeated 2023) relate NMAS contours to
# digital data as contour interval = 2 x LE90; Copernicus relative LE90 is < 2 m on
# slopes <= 20%, so 2 x 2 m = 4 m, rounded up to 5 m.
CONTOUR_FLOOR_M = 5.0

# ---------------------------------------------------------------------------
# sources quoted in flags (kept here so citations can be corrected in one place)
# ---------------------------------------------------------------------------
_GPP = ("PLANMalaysia (then JPBD Semenanjung Malaysia, KPKT), Garis Panduan Perancangan "
        "Pembangunan di Kawasan Bukit dan Tanah Tinggi (2009)")
SRC_GPP_CLASSES = f"{_GPP}, Jadual 1"
SRC_GPP_REPORTS = f"{_GPP}, Jadual 1 (technical reports for every class)"
SRC_GPP_BANDS = (f"{_GPP}, s.2 land categories and KSAS levels quoted from National "
                 "Physical Plan Policy 18")
_EIA = ("Environmental Quality (Prescribed Activities) (Environmental Impact Assessment) "
        "Order 2015, P.U. (A) 195/2015")
SRC_EIA_FOREST = f"{_EIA}, First Schedule 5(a) and Second Schedule 5(a)"
SRC_EIA_SLOPE = f"{_EIA}, First Schedule item 13 and Second Schedule item 13(a)"
SRC_EIA_ROUTE = f"{_EIA}, Second Schedule item 13(b)"
SRC_EIA_AREA = (f"{_EIA}, First Schedule items 5(a), 5(d) and 17; Second Schedule items "
                "3(b), 5(a) and 5(f); item 11 (power generation)")
SRC_EIA_SCOPE = f"{_EIA}, paragraph 4 (application in Sabah and Sarawak)"
SRC_SDBA = ("Street, Drainage and Building Act 1974 (Act 133), s.70(2)(c), inserted by "
            "Act A1588 (2019)")
SRC_PENANG = ("News reports (New Straits Times and RTM, 10 Dec 2025) on the Penang "
              "Structure Plan 2030 (RSNPP 2030, gazetted 24 Oct 2019) and the draft RSNPP 2040")
SRC_PAHANG_SOLAR = ("PLANMalaysia@Pahang, Garis Panduan Perancangan Pembangunan Tenaga "
                    "Solar Negeri Pahang (GPP PHG 03, 2022)")
SRC_PAHANG_HILL = ("Kaedah-Kaedah Kawalan Perancangan (Pemajuan Tanah Bukit, Tanah Tinggi "
                   "dan Lereng Bukit)(Pahang) 2019, as summarised in PLANMalaysia@Pahang's "
                   "JTKSAS monograph (2022 edition)")
SRC_PV_SLOPE = ("IFC (2015) Utility-Scale Solar Photovoltaic Power Plants: A Project "
                "Developer's Guide, s.6.3.4; Array Technologies DuraTrack HZ v3 and "
                "TrinaTracker Vanguard 1P datasheets; TrinaTracker FixOrigin brochure; "
                "NREL/TP-6A20-91900 (2024)")
SRC_CAPACITY = ("IFC (2015) Utility-Scale Solar Photovoltaic Power Plants: A Project "
                "Developer's Guide, Table 7")
SRC_MSMA = "Urban Stormwater Management Manual for Malaysia (MSMA), 2nd Edition (DID/JPS 2012)"
SRC_SURVEY = "Licensed Land Surveyors Act 1958 (Act 458)"

LEVEL_ORDER = {"warning": 0, "caution": 1, "info": 2}
EIA_CODES = ("eia_slope_item13", "eia_route_35", "eia_area_items", "eia_slope_state_regime")

STAMP_TEMPLATE = "Desktop screening — not a survey · DEM: {name} ({epoch}) · EcoEnergy Consultancy"
# Second footer line, by DEM provider (only where the licence asks for a credit).
STAMP_CREDITS = {"copernicus": COPERNICUS_STAMP_CREDIT}

# --- shared sentences ------------------------------------------------------------
GEOTECH_NOTE = (
    "The class shown is a slope-based indication only: the guideline also assigns classes by "
    "geotechnical condition (signs of erosion or instability, colluvium or other sensitive "
    "geological material, ex-mining land), so a geotechnical assessment can place ground "
    "in a higher class.")
SMA_NOTE = (
    "The guideline does not apply in the Special Management Areas of Cameron "
    "Highlands–Kinta Lojing, Genting Highlands–Bukit Tinggi–Janda Baik and Bukit Fraser, "
    "where the local authority's development plans govern; this screening does not check "
    "whether the site lies in one of them.")
NOT_LISTED_NOTE = "a solar farm is not among the uses it lists for any class"
NATIONAL_INFRA_NOTE = (
    "low-intensity infrastructure of national importance (roads, tunnels, bridges, "
    "telecommunications and electricity); the guideline does not say whether a solar "
    "farm could qualify")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _ok(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


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


def _state(result: dict) -> str | None:
    return (result.get("location") or {}).get("state") or None


def _limited_eia(state: str | None) -> bool:
    return state in EIA_LIMITED_SCOPE_STATES


def _kpkt(site: dict, *classes: str) -> float | None:
    """Sum of the site's KPKT shares for the given classes, or None if unknown."""
    vals = [(site.get("kpkt_pct") or {}).get(c) for c in classes]
    return sum(vals) if vals and all(_ok(v) for v in vals) else None


def _bins(site: dict) -> dict | None:
    bins = site.get("slope_bins_pct") or {}
    vals = [bins.get(label) for label, _, _ in SLOPE_BINS]
    return bins if all(_ok(v) for v in vals) else None


def share_steeper(site: dict, deg: float) -> float | None:
    """Estimated % of a site steeper than `deg`, from the slope bins: bins entirely above
    count in full, the bin containing `deg` counts in proportion (slopes assumed evenly
    spread within it). None when the site has no slope data."""
    bins = _bins(site)
    if bins is None:
        return None
    total = 0.0
    for label, lo, hi in SLOPE_BINS:
        if lo >= deg:
            total += bins[label]
        elif hi > deg and math.isfinite(hi):
            total += bins[label] * (hi - deg) / (hi - lo)
    return min(100.0, total)


def grade_share(site: dict, grade_pct: float) -> tuple[float | None, bool]:
    """(% of a site steeper than a grade, exact?). Uses the engine's exact share
    ("steeper_than_grade_pct") when present, else estimates it from the slope bins."""
    exact = (site.get("steeper_than_grade_pct") or {}).get(f"{grade_pct:g}")
    if _ok(exact):
        return exact, True
    return share_steeper(site, math.degrees(math.atan(grade_pct / 100.0))), False


def _elev_max(site: dict) -> float | None:
    v = site.get("elev_max_m")
    return v if _ok(v) else None


def _is_surface_model(dem: dict) -> bool:
    model = str(dem.get("model_type", ""))
    return "DSM" in model or "surface" in model.lower()


def _surface_note(dem: dict) -> str:
    if not _is_surface_model(dem):
        return ""
    return (" The DEM is a surface model, so under tree canopy or buildings the ground is "
            "lower than shown; check the band against surveyed levels.")


def _mwp_range(area_ha: float) -> str:
    """Gross MWp range for an area at HA_PER_MWP_HIGH..HA_PER_MWP_LOW, same precision at both ends."""
    lo, hi = area_ha / HA_PER_MWP_HIGH, area_ha / HA_PER_MWP_LOW
    nd = 0 if lo >= 10 else 1
    return f"{lo:,.{nd}f}–{hi:,.{nd}f}"


def figure_stamp(dem: dict) -> str:
    """Footer stamp printed on every figure (a second line carries the DEM credit where
    the provider's licence asks for one)."""
    # "December 2010 – January 2015 (TanDEM-X acquisitions)" ->
    # "December 2010 – January 2015, TanDEM-X acquisitions": no nested brackets.
    epoch = str(dem.get("epoch", "unknown"))
    if epoch.endswith(")") and " (" in epoch:
        epoch = epoch[:-1].replace(" (", ", ", 1)
    stamp = STAMP_TEMPLATE.format(name=dem.get("name", "unknown"), epoch=epoch)
    credit = STAMP_CREDITS.get(dem.get("provider"))
    return f"{stamp}\n{credit}" if credit else stamp


# ---------------------------------------------------------------------------
# hill and highland guideline (slope classes, elevation bands, technical reports)
# ---------------------------------------------------------------------------
_KPKT_RULES = {
    "II": ("caution", "kpkt_class_ii", "15° to under 25°",
           "Slopes of 15–25° inside the site (slope-based KPKT Class II)",
           "Jadual 1 rates Class II as moderate geotechnical constraint. "
           f"{GEOTECH_NOTE} Below 300 m the guideline lists urban uses that may be considered "
           f"on Class II ground, with intensity limits; {NOT_LISTED_NOTE}, so ask the local "
           "planning authority how it will treat one here."),
    "III": ("warning", "kpkt_class_iii", "25° to under 35°",
            "Slopes of 25–35° inside the site (slope-based KPKT Class III)",
            "Jadual 1 rates Class III as high geotechnical constraint. "
            f"{GEOTECH_NOTE} Below 300 m the guideline lists a narrower set of urban uses, at "
            f"lower intensity, that may be considered on Class III ground; {NOT_LISTED_NOTE}. For "
            "Class III the guideline asks for an EIA report for all development projects. "
            "Leave this ground out of early layouts until a survey and a geotechnical "
            "assessment say otherwise."),
    "IV": ("warning", "kpkt_class_iv", "35° or steeper",
           "Slopes of 35° or more inside the site (slope-based KPKT Class IV)",
           "Jadual 1 rates Class IV as extreme geotechnical constraint. "
           f"{GEOTECH_NOTE} At every elevation the guideline allows no development on Class IV "
           f"ground except {NATIONAL_INFRA_NOTE}. Where Class IV is less than "
           f"{KPKT_CLASS_IV_EXEMPTION_PCT:g}% of a site with mixed classes, the developer must "
           "apply for an exemption, which may be granted with stricter engineering works. The "
           "guideline asks for a detailed EIA for Class IV. A 30 m DEM understates steep "
           "ground, so confirm the Class IV share by survey, and leave it out of usable-area "
           "and capacity estimates."),
}


def kpkt_flags(sites: list[dict]) -> list[dict]:
    out = []
    for cls, (level, code, band, title, consequence) in _KPKT_RULES.items():
        hits = []
        for s in sites:
            pct = _kpkt(s, cls)
            if pct is None or pct <= KPKT_FLAG_MIN_PCT:
                continue
            hit = f"{_q(s['name'])}: {_fmt(pct)}% of its area"
            if cls == "IV":
                hit += (f" (under {KPKT_CLASS_IV_EXEMPTION_PCT:g}%)" if pct < KPKT_CLASS_IV_EXEMPTION_PCT
                        else f" ({KPKT_CLASS_IV_EXEMPTION_PCT:g}% or more)")
            hits.append(hit)
        if hits:
            out.append(_flag(level, code, title,
                             f"Share of site area at {band} on the DEM — {_join(hits)}. {consequence}",
                             SRC_GPP_CLASSES))
    return out


def _any_class_ii_plus(sites: list[dict]) -> bool:
    return any((_kpkt(s, c) or 0.0) > KPKT_FLAG_MIN_PCT for s in sites for c in ("II", "III", "IV"))


def all_class_i_flag(sites: list[dict]) -> dict | None:
    measured = [s for s in sites if _kpkt(s, "II", "III", "IV") is not None]
    if not measured or _any_class_ii_plus(measured):
        return None
    return _flag(
        "info", "all_class_i", "Site area screens as KPKT Class I by slope (below 15°)",
        f"No site has more than {KPKT_FLAG_MIN_PCT:g}% of its area at {KPKT_CLASS_II_MIN_DEG:g}° or "
        "steeper on this DEM, "
        "so by slope alone the land screens as KPKT Class I (low geotechnical constraint). "
        "Below 300 m the guideline lets all types of development be considered on Class I "
        "ground, subject to the local or development plan. This is a slope-based indication "
        "only: the guideline also places gentle ground in a higher class where it shows "
        "erosion or instability, lies on colluvium or other sensitive geological material, "
        "is limestone, swamp, peat or ex-mining land, or is under flood threat. A 30 m "
        "elevation model also smooths out short steep features such as bund faces, drain "
        "banks and cuttings.",
        SRC_GPP_CLASSES)


def _guideline_triggered(sites: list[dict]) -> bool:
    return _any_class_ii_plus(sites) or any(
        (_elev_max(s) or 0.0) >= TANAH_BUKIT_MIN_M for s in sites)


def guideline_reports_flag(sites: list[dict], state: str | None) -> dict | None:
    if not _guideline_triggered(sites):
        return None
    reasons = []
    if _any_class_ii_plus(sites):
        reasons.append(f"part of the site is at {KPKT_CLASS_II_MIN_DEG:g}° or steeper on the DEM")
    if any((_elev_max(s) or 0.0) >= TANAH_BUKIT_MIN_M for s in sites):
        reasons.append(f"the site reaches {TANAH_BUKIT_MIN_M:g} m or more on the DEM")
    detail = (
        f"Listed because {' and '.join(reasons)}. Where the 2009 hill and highland guideline "
        "applies, it asks for five technical reports for every slope class: (1) a geotechnical "
        "investigation and slope stability analysis by a geotechnical engineer; (2) geological "
        "and geomorphological mapping by a geologist registered with the Board of Geologists; "
        "(3) a drainage report under MSMA by a hydrology engineer registered with JPS; (4) an "
        "EIA report by a DOE-registered EIA consultant (the Class I and II pages add “for "
        "development over 50 hectares”; for Class III the guideline asks for an EIA for all "
        "development projects and for Class IV a detailed EIA); and (5) an earthworks plan by "
        "an engineer registered with BEM.")
    if _limited_eia(state):
        detail += (" The guideline was published by the then JPBD Semenanjung Malaysia; ask the "
                   f"state planning authority how hill-land development is controlled in {state}.")
    return _flag("info", "guideline_reports",
                 "Technical reports asked for under the hill and highland guideline",
                 detail, SRC_GPP_REPORTS)


def _band_hits(sites: list[dict], lo: float, hi: float) -> list[str]:
    hits = []
    for s in sites:
        top = _elev_max(s)
        if top is not None and lo <= top < hi:
            low = s.get("elev_min_m")
            hits.append(f"{_q(s['name'])}: up to {_fmt(top, 0)} m"
                        + (f" (lowest {_fmt(low, 0)} m)" if _ok(low) else ""))
    return hits


def _sma_note(state: str | None) -> str:
    # The Special Management Areas are all in Peninsular Malaysia.
    return "" if _limited_eia(state) else f" {SMA_NOTE}"


def _forest_note(state: str | None) -> str:
    if _limited_eia(state):
        return ""
    return (f" If any land at {EIA_FOREST_ELEVATION_M:g} m or more is forest, converting it to "
            "another land use is a prescribed activity under the EIA Order 2015 from "
            f"{EIA_FOREST_300M_FIRST_HA:g} ha (First Schedule item 5(a)) and, from "
            f"{EIA_FOREST_300M_SECOND_HA:g} ha, a Second Schedule activity with public display "
            "and public comment (item 5(a)).")


def hill_land_band_flag(sites: list[dict], dem: dict) -> dict | None:
    hits = _band_hits(sites, TANAH_BUKIT_MIN_M, TANAH_TINGGI_MIN_M)
    if not hits:
        return None
    return _flag(
        "caution", "hill_land_band", "Hill land elevation band (Tanah Bukit, 150–300 m)",
        f"Highest DEM elevation — {_join(hits)}. The 2009 hill and highland guideline treats "
        f"land at {TANAH_BUKIT_MIN_M:g}–{TANAH_TINGGI_MIN_M:g} m above sea level as Tanah Bukit "
        "(hill land) and, quoting the National Physical Plan, places it in KSAS Level 3: "
        "controlled development, with the type and intensity of development set by site "
        f"constraints.{_surface_note(dem)}",
        SRC_GPP_BANDS)


def highland_band_flag(sites: list[dict], dem: dict, state: str | None) -> dict | None:
    hits = _band_hits(sites, TANAH_TINGGI_MIN_M, GUNUNG_MIN_M)
    if not hits:
        return None
    return _flag(
        "warning", "highland_band", "Highland elevation band (Tanah Tinggi, 300–1,000 m)",
        f"Highest DEM elevation — {_join(hits)}. The 2009 hill and highland guideline treats "
        f"land above {TANAH_TINGGI_MIN_M:g} m and below {GUNUNG_MIN_M:,.0f} m as Tanah Tinggi "
        "(highland). There it lets only low-impact eco-tourism and recreation be considered "
        "(on Class III ground, only low-impact recreation without structures); a solar farm is "
        f"not a listed use.{_sma_note(state)}{_forest_note(state)}{_surface_note(dem)}",
        SRC_GPP_BANDS + ("" if _limited_eia(state) else f"; {SRC_EIA_FOREST}"))


def mountain_band_flag(sites: list[dict], dem: dict, state: str | None) -> dict | None:
    hits = _band_hits(sites, GUNUNG_MIN_M, math.inf)
    if not hits:
        return None
    return _flag(
        "warning", "mountain_band", "Mountain elevation band (Gunung, above 1,000 m)",
        f"Highest DEM elevation — {_join(hits)}. The 2009 hill and highland guideline treats "
        f"land above {GUNUNG_MIN_M:,.0f} m as Gunung (mountain), where no development is "
        f"allowed except {NATIONAL_INFRA_NOTE}.{_sma_note(state)}{_forest_note(state)}"
        f"{_surface_note(dem)}",
        SRC_GPP_BANDS + ("" if _limited_eia(state) else f"; {SRC_EIA_FOREST}"))


# ---------------------------------------------------------------------------
# EIA Order 2015
# ---------------------------------------------------------------------------
def _item13_hits(sites: list[dict]) -> list[tuple[dict, float]]:
    return [(s, pct) for s in sites
            if (pct := _kpkt(s, "III")) is not None and pct > KPKT_FLAG_MIN_PCT]


def _route35_hits(routes: list[dict]) -> list[dict]:
    return [r for r in routes if _ok(r.get("max_grade_pct")) and r["max_grade_pct"] >= EIA_ROUTE_GRADE_PCT]


def eia_slope_flag(sites: list[dict], state: str | None) -> dict | None:
    if _limited_eia(state):
        return None
    hits = []
    for s, pct in _item13_hits(sites):
        item = ("50% or more, which points to Second Schedule item 13(a)"
                if pct >= EIA_SLOPE_SECOND_SCHEDULE_PCT
                else "under 50%, which points to First Schedule item 13")
        hits.append(f"{_q(s['name'])}: {_fmt(pct)}% of its area ({item})")
    if not hits:
        return None
    return _flag(
        "warning", "eia_slope_item13", "EIA Order 2015 slope item: ground at 25–35°",
        f"Share of site area at {EIA_SLOPE_MIN_DEG:g}° to under {EIA_SLOPE_MAX_DEG:g}° on the "
        f"DEM — {_join(hits)}. The EIA Order 2015 lists “development or land clearing less than "
        "50 per cent of an area with slope greater than or equal to 25° but less than 35°” in "
        "the First Schedule (item 13), and “development or land clearing of 50 per cent or "
        "more” of such an area in the Second Schedule (item 13(a)), which also requires public "
        "display and public comment. The item sets no minimum area. A 30 m DEM understates "
        "slopes, so the true share at 25–35° may be higher. Have a DOE-registered EIA "
        "consultant confirm how the item applies to the planned layout.",
        SRC_EIA_SLOPE)


def eia_route_flag(routes: list[dict], state: str | None) -> dict | None:
    if _limited_eia(state):
        return None
    hits = [f"{_q(r['name'])}: {_fmt(r['max_grade_pct'], 0)}% grade "
            f"(about {_fmt(math.degrees(math.atan(r['max_grade_pct'] / 100.0)), 0)}°)"
            for r in _route35_hits(routes)]
    if not hits:
        return None
    return _flag(
        "warning", "eia_route_35", "Route crosses ground of 35° or steeper",
        f"Steepest stretch along the route on the DEM, measured over at least "
        f"{ROUTE_GRADE_WINDOW_M} m — {_join(hits)}. A grade of "
        f"{EIA_ROUTE_GRADE_PCT:.0f}% or more means the ground along that stretch is at least "
        f"{EIA_ROUTE_SLOPE_DEG:g}° steep. If an access road is built along this route, the EIA "
        "Order 2015 lists “construction of road, tunnel or bridge traversing an area with slope "
        "greater than or equal to 35°” in the Second Schedule (item 13(b)), which requires "
        "public display and public comment. A cable laid without a road may be assessed "
        "differently; confirm with a DOE-registered EIA consultant.",
        SRC_EIA_ROUTE)


def eia_state_regime_flag(sites: list[dict], routes: list[dict], state: str | None) -> dict | None:
    if not _limited_eia(state):
        return None
    hits = [f"{_q(s['name'])}: {_fmt(pct)}% of its area at 25° to under 35°"
            for s, pct in _item13_hits(sites)]
    hits += [f"{_q(r['name'])}: a {_fmt(r['max_grade_pct'], 0)}% grade (35° or steeper)"
             for r in _route35_hits(routes)]
    if not hits:
        return None
    return _flag(
        "info", "eia_slope_state_regime", f"Federal EIA slope items do not apply in {state}",
        f"On the DEM — {_join(hits)}. Elsewhere in Malaysia this ground could bring in the "
        "slope items (item 13) of the EIA Order 2015, but under paragraph 4 of the Order only a "
        f"limited set of items applies in {state}, and item 13 is not among them. Check the "
        "environmental assessment requirements for slope development with the state authority.",
        SRC_EIA_SCOPE)


def eia_area_flag(totals: dict, state: str | None) -> dict | None:
    area = totals.get("total_area_ha")
    if not (_ok(area) and area > 0):
        return None
    head = ("Solar PV is not listed among the power-generation items of the EIA Order 2015 "
            "at any capacity. ")
    if _limited_eia(state):
        return _flag(
            "info", "eia_area_items", f"EIA Order 2015: limited scope in {state}",
            f"{head}Under paragraph 4 of the Order only a limited set of items applies in "
            f"{state}: the forest-conversion items (5), the slope items (13), the First Schedule "
            "industrial-estate item (17) and the wetland-drainage item (Second Schedule 3(b)) are "
            "not among them. "
            f"The total polygon area is {_fmt(area, 2)} ha. Check the environmental assessment "
            "requirements for this site with the state authority.",
            SRC_EIA_SCOPE)
    unknown = (" The state could not be identified from the boundary data; note that in Sabah "
               "and Sarawak the Order applies only to a limited set of items." if state is None else "")
    pahang = (" Pahang's solar planning guideline describes a solar farm as an industrial "
              "activity, but that is not a DOE ruling." if state == PAHANG_STATE else "")
    return _flag(
        "info", "eia_area_items", "EIA Order 2015: area-based items to check",
        f"{head}Area-based items may still apply, depending on the land cover and what is "
        "cleared, converted or drained: First Schedule 5(a), conversion of forest at "
        f"{EIA_FOREST_ELEVATION_M:g} m or more above mean sea level to other land use, "
        f"{EIA_FOREST_300M_FIRST_HA:g} ha to under {EIA_FOREST_300M_SECOND_HA:g} ha (Second "
        f"Schedule 5(a): {EIA_FOREST_300M_SECOND_HA:g} ha or more); First Schedule 5(d), "
        "conversion of mangrove, peat swamp or freshwater swamp forest for industrial, housing "
        f"or agricultural use, {EIA_SWAMP_FOREST_FIRST_HA:g} ha to under "
        f"{EIA_SWAMP_FOREST_SECOND_HA:g} ha (Second Schedule 5(f): "
        f"{EIA_SWAMP_FOREST_SECOND_HA:g} ha or more); Second Schedule 3(b), drainage of wetland, "
        f"wildlife habitat or dry inland forest covering {EIA_WETLAND_DRAINAGE_HA:g} ha or more; "
        f"First Schedule 17, development of an industrial estate of {EIA_INDUSTRIAL_ESTATE_HA:g} "
        "ha or more — whether DOE treats a solar farm as an industrial estate is not settled."
        f"{pahang} The total polygon area is {_fmt(area, 2)} ha; the thresholds apply to the "
        "area actually cleared, converted or drained. Second Schedule activities also require "
        "public display and public comment. Have a DOE-registered EIA consultant confirm which "
        f"items apply.{unknown}",
        SRC_EIA_AREA)


# ---------------------------------------------------------------------------
# Act 133 and state-specific rules
# ---------------------------------------------------------------------------
def sdba_geotech_flag(sites: list[dict]) -> dict | None:
    hits = []
    for s in sites:
        steep = _kpkt(s, "III", "IV")
        relief = s.get("relief_m")
        if steep is not None and steep > KPKT_FLAG_MIN_PCT and _ok(relief) and relief > SDBA_HEIGHT_M:
            hits.append(f"{_q(s['name'])}: {_fmt(steep)}% of its area steeper than "
                        f"{SDBA_SLOPE_DEG:g}°, {_fmt(relief, 0)} m of relief")
    if not hits:
        return None
    return _flag(
        "caution", "sdba_geotech", "Act 133 geotechnical report for slopes over 25° and 10 m high",
        f"On the DEM — {_join(hits)}. Section 70(2)(c) of the Street, Drainage and Building Act "
        "1974 (Act 133), inserted by Act A1588 (2019), requires a geotechnical report, verified "
        "by an Accredited Checker, for “erection involving slope with a gradient more than "
        "twenty-five degrees and total vertical height more than ten metres”. The 25° and 10 m "
        "tests apply to an individual slope; site relief only shows that slopes of that height "
        "may exist. Check with the local authority whether the provision applies and is in "
        "force for this area.",
        SRC_SDBA)


def penang_hill_flag(sites: list[dict], dem: dict, state: str | None) -> dict | None:
    if state != PENANG_STATE:
        return None
    hits = []
    for s in sites:
        parts = []
        top, steep = _elev_max(s), _kpkt(s, "III", "IV")
        if top is not None and top > PENANG_HILL_M:
            parts.append(f"up to {_fmt(top, 0)} m")
        if steep is not None and steep > KPKT_FLAG_MIN_PCT:
            parts.append(f"{_fmt(steep)}% of its area steeper than {PENANG_SLOPE_DEG:g}°")
        if parts:
            hits.append(f"{_q(s['name'])}: {' and '.join(parts)}")
    if not hits:
        return None
    canopy = (" DEM heights include tree canopy and buildings, so the ground may be lower."
              if _is_surface_model(dem) else "")
    return _flag(
        "warning", "penang_hill", "Penang hill-land limits (76 m and 25°), as reported",
        f"On the DEM — {_join(hits)}.{canopy} News reports (New Straits Times and RTM, "
        "10 Dec 2025) say the Penang Structure Plan 2030 (RSNPP 2030, gazetted 24 Oct 2019) "
        f"prohibits development on hill land above {PENANG_HILL_M:g} m (250 ft) above sea level "
        f"or on slopes steeper than {PENANG_SLOPE_DEG:g}°. The limit is under review in the "
        "draft Penang Structure Plan 2040 (RSNPP 2040), whose public inspection closed on "
        "9 Sep 2026. This is as reported; verify the current status with PLANMalaysia@Pulau "
        "Pinang and the city council (MBPP/MBSP).",
        SRC_PENANG)


def pahang_solar_flag(sites: list[dict], state: str | None) -> dict | None:
    if state != PAHANG_STATE:
        return None
    hits = [f"{_q(s['name'])}: {_fmt(pct)}%" for s in sites
            if (pct := share_steeper(s, PAHANG_SOLAR_MAX_DEG)) is not None and pct > KPKT_FLAG_MIN_PCT]
    if not hits:
        return None
    detail = (
        f"Share of site area steeper than {PAHANG_SOLAR_MAX_DEG:g}° on the DEM — {_join(hits)}. "
        "PLANMalaysia@Pahang's solar planning guideline (GPP PHG 03, 2022) says solar farms suit "
        "flat and gently sloping land, that terrain steeper than 10 degrees is not suitable "
        "(“Keadaan topografi yang berkecerunan melebihi 10 darjah adalah tidak sesuai”), and "
        "that site clearing and earthworks must be kept to a minimum.")
    source = SRC_PAHANG_SOLAR
    reasons = []
    if any((_elev_max(s) or 0.0) >= PAHANG_JTKSAS_ELEV_M for s in sites):
        reasons.append(f"the site reaches {PAHANG_JTKSAS_ELEV_M:g} m or more")
    if any((_kpkt(s, "III", "IV") or 0.0) > KPKT_FLAG_MIN_PCT for s in sites):
        reasons.append(f"part of the site is at {PAHANG_JTKSAS_SLOPE_DEG:g}° or steeper")
    if reasons:
        detail += (
            f" Because {' and '.join(reasons)} on the DEM, note also Pahang's Kaedah-Kaedah "
            "Kawalan Perancangan (Pemajuan Tanah Bukit, Tanah Tinggi dan Lereng Bukit)(Pahang) "
            "2019: urban development applications (housing, commercial, tourism and industrial) "
            f"on highland at {PAHANG_JTKSAS_ELEV_M:g} m or more, or on slopes of "
            f"{PAHANG_JTKSAS_SLOPE_DEG:g}° or more, are reviewed by the state KSAS Technical "
            "Committee (JTKSAS); different criteria apply in Cameron Highlands, Genting "
            "Highlands, Bukit Tinggi and Janda Baik.")
        source += f"; {SRC_PAHANG_HILL}"
    return _flag("warning", "pahang_solar_10deg",
                 "Pahang solar guideline: terrain steeper than 10° is not suitable", detail, source)


# ---------------------------------------------------------------------------
# ground-mounted PV: slope context and indicative capacity
# ---------------------------------------------------------------------------
_PV_CONTEXT = (
    "IFC's 2015 solar developer guide (s.6.3.4) says a site should ideally be flat or on a "
    "slight south-facing slope (northern hemisphere) and that mounting structures can be "
    "designed for most locations at extra cost and complexity; it gives no numeric limit. "
    "For context, published product figures include a standard north–south slope tolerance "
    "of 15% for two single-axis trackers (Array Technologies DuraTrack HZ v3, with 26% as an "
    "option; TrinaTracker Vanguard 1P, also 15% east–west) and standard conditions up to 10% "
    "for one fixed-tilt structure (TrinaTracker FixOrigin); NREL's 2024 US supply-curve study "
    "excludes slopes over 10% in its Reference scenario (5% in its Limited scenario). These "
    "figures do not show whether any product suits this site: tolerances depend on the slope "
    "direction relative to the rows and must come from the chosen supplier.")


def steep_for_ground_pv_flag(sites: list[dict]) -> dict | None:
    rows, estimated = [], False
    for s in sites:
        (hi, hi_exact), (lo, lo_exact) = (grade_share(s, PV_GRADE_TRACKER_PCT),
                                          grade_share(s, PV_GRADE_FIXED_PCT))
        if hi is not None and lo is not None:
            rows.append((s, hi, lo))
            estimated |= not (hi_exact and lo_exact)

    def hit(s, hi, lo):
        return f"{_q(s['name'])}: {_fmt(hi, 0)}% and {_fmt(lo, 0)}%"

    lead = (f"Share of site area steeper than about {PV_SLOPE_TRACKER_DEG:.1f}° (a "
            f"{PV_GRADE_TRACKER_PCT:g}% grade) and steeper than about {PV_SLOPE_FIXED_DEG:.1f}° "
            f"(a {PV_GRADE_FIXED_PCT:g}% grade) on the DEM — ")
    method = (" Shares are estimated from the slope bands, assuming slopes are spread evenly "
              "within each band." if estimated else "")
    steep = [hit(*r) for r in rows if r[1] > STEEP_PV_AREA_PCT]
    if steep:
        return _flag(
            "caution", "steep_for_ground_pv",
            f"More than {STEEP_PV_AREA_PCT:g}% of a site is steeper than about "
            f"{PV_SLOPE_TRACKER_DEG:.1f}° ({PV_GRADE_TRACKER_PCT:g}% grade)",
            f"{lead}{_join(steep)}.{method} {_PV_CONTEXT} This ground may need grading, "
            "terracing or special piling, adding earthworks and erosion-control cost.",
            SRC_PV_SLOPE)
    gentle = [hit(*r) for r in rows if r[2] > STEEP_PV_AREA_PCT]
    if gentle:
        return _flag(
            "info", "steep_for_ground_pv",
            f"More than {STEEP_PV_AREA_PCT:g}% of a site is steeper than about "
            f"{PV_SLOPE_FIXED_DEG:.1f}° ({PV_GRADE_FIXED_PCT:g}% grade)",
            f"{lead}{_join(gentle)}. No site has more than {STEEP_PV_AREA_PCT:g}% of its area "
            f"steeper than about {PV_SLOPE_TRACKER_DEG:.1f}°.{method} {_PV_CONTEXT}",
            SRC_PV_SLOPE)
    return None


def indicative_capacity_flag(sites: list[dict], totals: dict) -> dict | None:
    area = totals.get("total_area_ha")
    if not (_ok(area) and area >= CAPACITY_MIN_AREA_HA):
        return None
    flatter, measured, estimated, any_steep = 0.0, 0, False, False
    for s in sites:
        pct, exact = grade_share(s, PV_GRADE_TRACKER_PCT)
        if pct is not None and _ok(s.get("area_ha")):
            flatter += s["area_ha"] * (100.0 - pct) / 100.0
            measured += 1
            estimated |= not exact
            any_steep |= pct > 0
    detail = (
        f"Using IFC (2015) Table 7, about {HA_PER_MWP_LOW:g}–{HA_PER_MWP_HIGH:g} ha per MWp for "
        "crystalline-silicon ground-mounted PV in Thailand and Indonesia (the closest climates "
        f"listed): the total polygon area of {_fmt(area, 2)} ha gives about "
        f"{_mwp_range(area)} MWp")
    if measured == len(sites) and not any_steep:
        detail += (f"; on the DEM all of it is flatter than about {PV_SLOPE_TRACKER_DEG:.1f}° "
                   f"({PV_GRADE_TRACKER_PCT:g}% grade)")
    elif measured:
        detail += (
            f"; the {_fmt(flatter, 1)} ha flatter than about {PV_SLOPE_TRACKER_DEG:.1f}° "
            f"({PV_GRADE_TRACKER_PCT:g}% grade) on the DEM gives about {_mwp_range(flatter)} MWp"
            + (" (flatter area estimated from the slope bands, assuming slopes are spread evenly "
               "within each band)" if estimated else ""))
    detail += (
        ". These are gross figures, before setbacks, access roads, drainage reserves, shading, "
        "steep or unsuitable ground and grid limits; the exact area per MWp varies with the "
        "tilt angle and row spacing (pitch).")
    return _flag("info", "indicative_capacity", "Indicative gross capacity from site area",
                 detail, SRC_CAPACITY)


# ---------------------------------------------------------------------------
# other terrain, data and route rules
# ---------------------------------------------------------------------------
def high_relief_flag(sites: list[dict]) -> dict | None:
    hits = [f"{_q(s['name'])}: {_fmt(s['relief_m'], 0)} m" for s in sites
            if _ok(s.get("relief_m")) and s["relief_m"] > HIGH_RELIEF_M]
    if not hits:
        return None
    return _flag(
        "info", "high_relief", f"More than {HIGH_RELIEF_M:g} m of elevation change within a site",
        f"Elevation range (highest minus lowest point) — {_join(hits)}. Plan for an earthworks "
        "balance and for stormwater and erosion control designed to MSMA 2nd Edition (DID/JPS "
        "2012) at design stage, and allow for them in early cost estimates.",
        SRC_MSMA)


def fpv_flags(sites: list[dict], dem: dict) -> list[dict]:
    water = (", and water bodies were flattened during editing, so it says nothing about depth"
             if dem.get("provider") == "copernicus" else "")
    out = [_flag(
        "info", "fpv_dem_epoch", "The elevation model cannot see the pond bed",
        f"The {dem['name']} was acquired in {dem['epoch']}. Ponds excavated or flooded after "
        "that do not appear in it. Where water was present it records the water surface, not "
        f"the bed{water}; the slope and KPKT figures for a pond therefore describe its water "
        "surface only. For floating solar, a bathymetric survey, seasonal water-level records "
        "and the condition of the bunds govern the design — no elevation model provides them.")]
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
        "than a 30 m DEM shows, and a route that crosses a slope at an angle has a lower grade "
        "than the slope itself.")


# ---------------------------------------------------------------------------
# public builders
# ---------------------------------------------------------------------------
def build_flags(result: dict) -> list[dict]:
    """Flags for a result dict (needs meta, dem, location, totals, sites, routes), most
    severe first."""
    sites, routes = result.get("sites", []), result.get("routes", [])
    dem, totals = result["dem"], result["totals"]
    scheme = (result.get("meta") or {}).get("scheme")
    state = _state(result)
    candidates: list[dict | None] = [
        *kpkt_flags(sites),
        all_class_i_flag(sites) if scheme != "fpv" else None,   # meaningless over water
        mountain_band_flag(sites, dem, state),
        highland_band_flag(sites, dem, state),
        hill_land_band_flag(sites, dem),
        penang_hill_flag(sites, dem, state),
        pahang_solar_flag(sites, state),
        eia_slope_flag(sites, state),
        eia_route_flag(routes, state),
        sdba_geotech_flag(sites),
        steep_for_ground_pv_flag(sites) if scheme not in PV_FLAG_EXEMPT_SCHEMES else None,
        *(fpv_flags(sites, dem) if scheme == "fpv" else []),
        guideline_reports_flag(sites, state),
        indicative_capacity_flag(sites, totals) if scheme in CAPACITY_SCHEMES else None,
        high_relief_flag(sites),
        small_site_flag(sites),
        dem_nodata_flag(dem),
        route_grade_flag(routes),
        eia_state_regime_flag(sites, routes, state),
        eia_area_flag(totals, state),
    ]
    flags = [f for f in candidates if f]
    return sorted(flags, key=lambda f: LEVEL_ORDER[f["level"]])   # stable within a level


def build_followups(result: dict) -> list[dict]:
    scheme = (result.get("meta") or {}).get("scheme")
    codes = {f["code"] for f in (result.get("flags") or build_flags(result))}
    out = [
        {"title": "Licensed topographic survey",
         "detail": "Before layout, earthworks or drainage design, commission a topographic survey "
                   "by a licensed land surveyor (Licensed Land Surveyors Act 1958, Act 458), or "
                   "LiDAR / drone photogrammetry tied to surveyed ground control points."},
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
    guideline = "guideline_reports" in codes
    if guideline:
        geotech = ("Commission a geotechnical investigation and slope stability analysis by a "
                   "geotechnical engineer before any layout or earthworks decision; the hill and "
                   "highland guideline asks for it for every slope class.")
        if "sdba_geotech" in codes:
            geotech += (" Where Act 133 s.70(2)(c) applies (a slope steeper than 25° and more than "
                        "10 m high), the geotechnical report must be verified by an Accredited "
                        "Checker.")
        out += [
            {"title": "Geotechnical investigation and slope stability analysis", "detail": geotech},
            {"title": "Geological and geomorphological mapping",
             "detail": "Commission geological and geomorphological mapping by a geologist "
                       "registered with the Board of Geologists, as the guideline asks; it also "
                       "identifies colluvium, ex-mining ground and other conditions that can put "
                       "ground in a higher KPKT class than its slope suggests."},
        ]
    if guideline or "high_relief" in codes:
        out.append({"title": "Drainage report to MSMA",
                    "detail": "Have a hydrology engineer registered with JPS prepare the drainage "
                              "and stormwater report to MSMA 2nd Edition (DID/JPS 2012), "
                              "including erosion and sediment control during earthworks."})
    if guideline:
        out.append({"title": "Earthworks plan",
                    "detail": "Have an engineer registered with BEM prepare the earthworks plan. "
                              "The guideline keeps hill cutting to a minimum and does not allow "
                              "cutting hills to level a whole development site."})
    if codes & set(EIA_CODES) or {"highland_band", "mountain_band"} & codes:
        out.append({"title": "Confirm EIA applicability with a DOE-registered EIA consultant",
                    "detail": "Have a DOE-registered EIA consultant check the layout, land cover "
                              "and areas to be cleared against the First and Second Schedules of "
                              "the EIA Order 2015 (in Sabah and Sarawak, against the state's "
                              "requirements) before committing to the site."})
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
    provider = dem.get("provider")
    model = str(dem.get("model_type", ""))
    spacing = _fmt(dem.get("grid_spacing_m"), 0)
    out = [
        "Screening grade only: this is a desktop terrain screening from an open global elevation "
        f"model. It is not a survey under the {SRC_SURVEY}, not engineering design, and not for "
        "planning applications or any other authority submission.",
    ]
    if provider == "copernicus":
        out += [
            f"The {dem['name']} is a digital surface model (DSM): vegetation and buildings were "
            "not removed, so plantations, forest and built-up areas read higher than the ground "
            "beneath them, and slopes at their edges can be exaggerated. Water bodies were "
            "flattened during editing, so over water it shows a level surface and nothing about "
            "depth.",
            "Accuracy: the Copernicus DEM specification is an absolute vertical accuracy better "
            "than 4 m and a relative vertical accuracy better than 2 m on slopes up to 20% (4 m on "
            "steeper slopes), both as 90% linear error (LE90). Independent checks are weaker under "
            "forest: in a global study against ICESat-2 ground heights where canopy cover exceeded "
            "50%, 90% of errors "
            "were within 26.55 m and the mean error was +12.09 m, so the model read high (Hawker et "
            "al. 2022, Environ. Res. Lett. 17 024016). Against 38 GNSS benchmarks in Perlis, "
            "Malaysia, its RMSE was 2.45 m (Sibaruddin et al. 2026).",
        ]
    elif _is_surface_model(dem):
        out.append(
            f"The {dem['name']} is a surface model: it records the top of tree canopy and "
            "buildings, not bare ground. Plantations, forest and built-up areas read higher than "
            "the ground beneath them, and slopes at their edges can be exaggerated.")
        if provider == "opentopodata":
            out.append(
                "Accuracy: SRTM was designed for an absolute height error under 16 m (90%); measured "
                "absolute height errors by continent were about 6–9 m at 90% (Farr et al. 2007).")
    else:
        out.append(f"Elevation model type: {model}. Check whether it represents bare ground or "
                   "the top of vegetation and buildings before relying on it.")
    out += [
        f"Elevations show the surface as it was in {dem['epoch']}. Ponds, cuttings, platforms and "
        "buildings made since then are not represented.",
        f"Slopes are computed on a grid of about {spacing} m (nominal "
        f"{dem['nominal_resolution_m']} m resolution). Each slope value averages over "
        "neighbouring cells, so short steep features such as bund faces, drain banks, stream "
        "banks and cuttings are smoothed out, and the shares of ground steeper than 15°, 25° and "
        "35° are likely to be understated.",
    ]
    interval = _fmt(result.get("contour_interval_m"), 0)
    if provider == "copernicus":
        out.append(
            f"Contours are drawn every {interval} m; this tool never draws them finer than "
            f"{CONTOUR_FLOOR_M:g} m. The ASPRS Positional Accuracy Standards (2014, repeated in "
            "2023) relate a contour "
            "interval to digital elevation data as twice the 90% vertical error (LE90); with the "
            "specified relative LE90 of under 2 m on slopes up to 20%, that is up to about 4 m, so "
            f"{CONTOUR_FLOOR_M:g} m is the finest honest interval for this model. Contours are for "
            "context, not design.")
    else:
        out.append(f"Contours are drawn every {interval} m for context only; they are no more "
                   "accurate than the elevation model.")
    out += [
        "Slope direction (aspect) is not assessed. At Malaysian latitudes (about 1–7°N) it is "
        "secondary to earthworks, drainage and geotechnics: the Global Solar Atlas gives optimum "
        "fixed tilts of only 2–8° at four sample points across Malaysia, gaining under 1% over "
        "horizontal. IFC (2015, s.6.3.4) says a site should ideally be flat or on a slight "
        "south-facing slope in the northern hemisphere.",
        "State and district come from DOSM boundaries at the centroid of the uploaded features "
        "and are for orientation; the state-specific notes depend on that lookup. Local authority "
        "areas, Special Management Areas, forest reserves and land titles are not checked.",
        "Regulatory notes summarise published instruments and, where marked, news reports. They "
        "are a screening aid, not legal advice; requirements change and are applied by the "
        "relevant authorities, so confirm them before relying on them.",
    ]
    if dem.get("sends_coordinates_to_third_party"):
        out.append("To fetch elevations, the site's coordinates were sent to an outside elevation "
                   "service (the OpenTopoData public API).")
    out.append("Site geometry is used exactly as supplied in the uploaded KML/KMZ file; it has not "
               "been checked against title plans or survey boundaries.")
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
    class_part = (f"; by slope alone, {_fmt(class_i)}% of the site area is Class I (below 15°)"
                  if _ok(class_i) else "")
    surface = ("; tree canopy and buildings are included in the surface"
               if _is_surface_model(dem) else "")
    return [
        {"file": "1_site_layout.png", "title": "Site layout",
         "caption": "Site boundaries, routes and points as supplied in the KML, with areas in "
                    f"hectares, on a local UTM grid ({epsg})."},
        {"file": "2_elevation.png", "title": "Elevation and contours",
         "caption": f"Shaded {dem['name']} elevation with contours every "
                    f"{_fmt(result.get('contour_interval_m'), 0)} m{surface}."},
        {"file": "3_slope_classes.png", "title": "Slope classes",
         "caption": "Slope from the elevation model in seven bands, with the KPKT slope-class "
                    f"boundaries at 15°, 25° and 35°{class_part}."},
        {"file": "4_profiles.png", "title": "Terrain profiles",
         "caption": f"West–east and south–north sections {through}{route_part}; the vertical "
                    "scale is exaggerated and not to scale."},
    ]
