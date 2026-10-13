"""The four screening figures, drawn with matplotlib's object-oriented API.

pyplot is never imported: it keeps global state and is not safe in the worker thread.
Each figure is a ``matplotlib.figure.Figure`` rendered by ``FigureCanvasAgg``.

Maps use a local UTM frame (km from the frame's south-west corner). DEM cells are
drawn as a curvilinear mesh of their projected corners, so the grid and the KML
geometry line up exactly.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LightSource, LinearSegmentedColormap, Normalize, to_rgb
from matplotlib.cm import ScalarMappable
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import PathPatch, Patch, Rectangle
from matplotlib.path import Path as MplPath
from matplotlib import patheffects
from pyproj import Transformer
from shapely.geometry.polygon import orient

from .analysis import SLOPE_BINS, Analysis

# --- brand ---
NAVY = "#0F2742"
GOLD = "#D4A23A"
PAPER = "#F4EFE6"
INK_MUTED = "#5A6472"
GRID = "#D9D3C7"
NODATA_RGB = to_rgb("#C9D3DD")          # blue-grey: open sea / voids, distinct from the grey buffer

DPI = 150
MAP_MAX_W, MAP_MAX_H, MAP_MIN_H = 8.0, 8.6, 4.2   # inches for the map panel itself
FOOTER_RECT = (0, 0.03, 1, 0.97)          # bottom 3% for the footer stamp (resized per stamp)
FOOTER_FONT_PT = 7
FOOTER_GAP_IN = 0.1                       # clear space between the footer and the plot decorations

# Sequential ramps: one hue family, lightness monotonic (light = low/gentle, dark =
# high/steep), adjacent steps >= 0.06 OKLCH L apart, so they read in greyscale print and
# for colour-blind readers (checked with the dataviz ordinal palette validator).
ELEV_CMAP = LinearSegmentedColormap.from_list(
    "eco_elevation", ["#A4C081", "#85AC6F", "#669461", "#4A7C52", "#336445", "#224C37"])
ELEV_MIN_SPAN_M = 10.0                    # flat sites must look flat: never stretch < 10 m
HILLSHADE_EXAG = 1.5
# Slope bins (analysis.SLOPE_BINS order): pale sand -> dark crimson, darker = steeper,
# with a larger lightness jump at each KPKT boundary (15/25/35°) so Class II+ stands out.
# The lightest step is deliberately pale ("flat reads calm"); it is always drawn inside a
# site outline, and legend swatches carry an edge.
SLOPE_COLOURS = ("#EFE8BA", "#E5D090", "#DCB563", "#D59739", "#CA5B00", "#A72721", "#65183D")
# Buffer (outside-site) cells: one light grey per slope bin, indexed like SLOPE_COLOURS.
# A fixed step per bin keeps the ramp monotonic; deriving greys from the colours'
# luminance collapsed the three palest bins (0-10 deg) into a single shade.
BUFFER_GREYS = np.repeat(np.linspace(0.95, 0.62, len(SLOPE_COLOURS))[:, None], 3, axis=1)
SLOPE_LABELS = ("0–2°", "2–5°", "5–10°", "10–15°", "15–25°", "25–35°", "≥ 35°")
# KPKT class -> indices of SLOPE_BINS it spans.
KPKT_GROUPS = (("KPKT Class I  (< 15°)", (0, 1, 2, 3)), ("KPKT Class II  (15–25°)", (4,)),
               ("KPKT Class III  (25–35°)", (5,)), ("KPKT Class IV  (≥ 35°)", (6,)))
MAX_ROUTE_PANELS = 4
PROFILE_MIN_SPAN_M = 10.0

_HALO = [patheffects.withStroke(linewidth=3.6, foreground="white")]
_ROUTE_HALO = [patheffects.withStroke(linewidth=4.6, foreground=NAVY)]


def _mpl(text: str) -> str:
    """Escape user text for matplotlib: an unescaped pair of '$' switches on mathtext.
    Outside math mode matplotlib shows backslashes literally and turns '\\$' into '$'."""
    return str(text).replace("$", r"\$")


def _short(text: str, n: int = 34) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def _nice(x: float) -> float:
    if x <= 0:
        return 1.0
    e = math.floor(math.log10(x))
    f = x / 10 ** e
    return (1 if f < 2 else 2 if f < 5 else 5) * 10 ** e


def _edges(c: np.ndarray) -> np.ndarray:
    mid = (c[:-1] + c[1:]) / 2
    return np.concatenate([[c[0] - (mid[0] - c[0])], mid, [c[-1] + (c[-1] - mid[-1])]])


class _Frame:
    """Local UTM km coordinates for the analysis frame."""

    def __init__(self, an: Analysis):
        self.tr = Transformer.from_crs("EPSG:4326", an.utm_epsg, always_xy=True)
        lons, lats = an.dem.lons, an.dem.lats
        ex, ey = self.tr.transform(*np.meshgrid(_edges(lons), _edges(lats)))
        self.x0, self.y0 = float(ex.min()), float(ey.min())
        self.Xe, self.Ye = (ex - self.x0) / 1000.0, (ey - self.y0) / 1000.0
        self.Xc, self.Yc = self.xy(*np.meshgrid(lons, lats))
        # Inner rectangle of the (slightly rotated) projected frame: no blank wedges.
        self.xlim = (float(self.Xe[:, 0].max()), float(self.Xe[:, -1].min()))
        self.ylim = (float(self.Ye[0, :].max()), float(self.Ye[-1, :].min()))

    def xy(self, lons, lats):
        x, y = self.tr.transform(np.asarray(lons, dtype=float), np.asarray(lats, dtype=float))
        return (np.asarray(x) - self.x0) / 1000.0, (np.asarray(y) - self.y0) / 1000.0


# ---------------------------------------------------------------------------
# shared drawing helpers
# ---------------------------------------------------------------------------
def _new_figure(size) -> Figure:
    fig = Figure(figsize=size, dpi=DPI, facecolor="white", layout="constrained")
    fig.get_layout_engine().set(rect=FOOTER_RECT, h_pad=0.06, w_pad=0.06)
    FigureCanvasAgg(fig)
    return fig


def _map_figure(frame: _Frame, side_w: float) -> Figure:
    """Figure sized to the frame's aspect ratio (no big empty bands), plus side_w inches
    on the right for a colour bar or legend."""
    w = frame.xlim[1] - frame.xlim[0]
    h = frame.ylim[1] - frame.ylim[0]
    aspect = h / w if w > 0 else 1.0
    map_w = MAP_MAX_W
    map_h = map_w * aspect
    if map_h > MAP_MAX_H:
        map_h, map_w = MAP_MAX_H, MAP_MAX_H / aspect
    map_h = max(map_h, MAP_MIN_H)
    return _new_figure((max(map_w + 1.0 + side_w, 7.5), map_h + 1.7))


def _titles(fig: Figure, ax, title: str, subtitle: str) -> None:
    fig.suptitle(title, x=0.02, ha="left", fontsize=13, fontweight="bold", color=NAVY)
    ax.set_title(subtitle, loc="left", fontsize=8.5, color=INK_MUTED)


def _footer(fig: Figure, stamp: str) -> None:
    """Footer stamp (one or two lines) at the bottom-left. The constrained layout is
    confined to the area above the stamp's measured height, so axis labels never overlap it."""
    text = fig.text(0.01, 0.008, _mpl(stamp), fontsize=FOOTER_FONT_PT, color=INK_MUTED,
                    ha="left", va="bottom", linespacing=1.35)
    top = text.get_window_extent(fig.canvas.get_renderer()).y1 / fig.bbox.height
    frac = min(0.2, top + FOOTER_GAP_IN / fig.get_figheight())
    fig.get_layout_engine().set(rect=(0, frac, 1, 1 - frac))


def _map_axes(fig: Figure, frame: _Frame, epsg: str):
    ax = fig.add_subplot(1, 1, 1)
    ax.set_xlim(*frame.xlim)
    ax.set_ylim(*frame.ylim)
    ax.set_aspect("equal")
    ax.set_xlabel(f"Easting (km, local {epsg} frame)", fontsize=8.5, color=INK_MUTED)
    ax.set_ylabel("Northing (km)", fontsize=8.5, color=INK_MUTED)
    ax.tick_params(labelsize=8, colors=INK_MUTED)
    for s in ax.spines.values():
        s.set_color(GRID)
    return ax


def _poly_path(frame: _Frame, poly) -> MplPath:
    poly = orient(poly, 1.0)               # exterior CCW, holes CW: holes render as holes
    verts, codes = [], []
    for ring in [poly.exterior, *poly.interiors]:
        x, y = frame.xy(*ring.xy)
        verts.extend(zip(x, y))
        codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(x) - 2) + [MplPath.CLOSEPOLY]
    return MplPath(verts, codes)


def _draw_outlines(ax, frame: _Frame, an: Analysis, lw: float = 1.8) -> None:
    for s in an.sites:
        ax.add_patch(PathPatch(_poly_path(frame, s.polygon), facecolor="none", edgecolor=NAVY,
                               lw=lw, path_effects=_HALO, zorder=5))


def _draw_routes_points(ax, frame: _Frame, an: Analysis, labels: bool = True) -> None:
    for r in an.routes:
        x, y = frame.xy(*zip(*r.coords))
        ax.plot(x, y, color=GOLD, lw=2.2, path_effects=_ROUTE_HALO, zorder=6,
                solid_capstyle="round")
    for p in an.points:
        x, y = frame.xy([p.lon], [p.lat])
        ax.plot(x, y, marker="^", ms=9, color=NAVY, mec="white", mew=1.2, ls="none", zorder=7)
        if labels:
            ax.annotate(_mpl(_short(p.name, 28)), (x[0], y[0]), xytext=(7, 5),
                        textcoords="offset points", fontsize=8, color=NAVY, zorder=8,
                        path_effects=_HALO)


def _north_arrow(ax) -> None:
    """Grid-north arrow in the lower-right corner on a white backing (UTM grid north is
    within ~0.5° of true north across Malaysia)."""
    x = 0.955
    ax.add_patch(Rectangle((x - 0.03, 0.025), 0.06, 0.13, transform=ax.transAxes,
                           facecolor="white", edgecolor="none", alpha=0.85, zorder=9))
    ax.annotate("", xy=(x, 0.125), xytext=(x, 0.04), xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", lw=2, color=NAVY, mutation_scale=14), zorder=10)
    ax.text(x, 0.125, "N", transform=ax.transAxes, ha="center", va="bottom",
            fontsize=10, fontweight="bold", color=NAVY, zorder=10)


def _scale_bar(ax, frame: _Frame) -> None:
    w = frame.xlim[1] - frame.xlim[0]
    h = frame.ylim[1] - frame.ylim[0]
    length = _nice(w / 5)                  # km
    x, y = frame.xlim[0] + 0.04 * w, frame.ylim[0] + 0.04 * h
    bh = 0.012 * h
    ax.add_patch(Rectangle((x - 0.015 * w, y - 0.025 * h), length + 0.03 * w, 0.075 * h,
                           facecolor="white", edgecolor="none", alpha=0.85, zorder=9))
    for k in range(4):
        ax.add_patch(Rectangle((x + k * length / 4, y), length / 4, bh, zorder=10,
                               facecolor=NAVY if k % 2 == 0 else "white", edgecolor=NAVY, lw=0.8))
    label = f"{length * 1000:g} m" if length < 1 else f"{length:g} km"
    ax.text(x, y + bh * 1.6, "0", fontsize=7.5, ha="center", va="bottom", color=NAVY, zorder=10)
    ax.text(x + length, y + bh * 1.6, label, fontsize=7.5, ha="center", va="bottom",
            color=NAVY, zorder=10)


def _save(fig: Figure, path: Path) -> None:
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor())


# ---------------------------------------------------------------------------
# 1. site layout
# ---------------------------------------------------------------------------
def draw_site_layout(an: Analysis, path: Path, stamp: str) -> None:
    frame = _Frame(an)
    fig = _map_figure(frame, 0.0)
    ax = _map_axes(fig, frame, an.utm_epsg)
    ax.set_facecolor(PAPER)
    ax.grid(color="white", lw=0.8, zorder=0)
    many = len(an.sites) > 8
    for s in an.sites:
        ax.add_patch(PathPatch(_poly_path(frame, s.polygon), facecolor=GOLD, alpha=0.30,
                               edgecolor="none", zorder=3))
    _draw_outlines(ax, frame, an, lw=2.0)
    for s in an.sites:
        rp = s.polygon.representative_point()
        x, y = frame.xy([rp.x], [rp.y])
        ax.text(x[0], y[0], f"{_mpl(_short(s.name))}\n{s.area_ha:,.1f} ha", ha="center",
                va="center", fontsize=7.5 if many else 9.5, fontweight="bold", color=NAVY,
                path_effects=_HALO, zorder=8)
    _draw_routes_points(ax, frame, an)
    for r in an.routes:   # name + length at the route's midpoint
        mid = r.lons.size // 2
        x, y = frame.xy([r.lons[mid]], [r.lats[mid]])
        ax.annotate(f"{_mpl(_short(r.name, 24))}\n{r.length_m / 1000:,.2f} km", (x[0], y[0]),
                    xytext=(8, -8), textcoords="offset points", fontsize=8, color=NAVY,
                    va="top", path_effects=_HALO, zorder=8)
    handles = []
    if an.sites:
        handles.append(Patch(facecolor=(*to_rgb(GOLD), 0.3), edgecolor=NAVY, lw=1.6,
                             label="Site boundary (KML)"))
    if an.routes:
        handles.append(Line2D([], [], color=GOLD, lw=2.2, path_effects=_ROUTE_HALO,
                              label="Route / cable line"))
    if an.points:
        handles.append(Line2D([], [], marker="^", ms=8, color=NAVY, mec="white", ls="none",
                              label="Point"))
    if handles:
        ax.legend(handles=handles, loc="upper left", fontsize=8, frameon=True, framealpha=0.9,
                  edgecolor=GRID)
    _north_arrow(ax)
    _scale_bar(ax, frame)
    total_ha = sum(s.area_ha for s in an.sites)
    bits = []
    if an.sites:
        bits.append(f"{len(an.sites)} site{'s' if len(an.sites) != 1 else ''}, {total_ha:,.1f} ha")
    if an.routes:
        km = sum(r.length_m for r in an.routes) / 1000
        bits.append(f"{len(an.routes)} route{'s' if len(an.routes) != 1 else ''}, {km:,.2f} km")
    if an.points:
        bits.append(f"{len(an.points)} point{'s' if len(an.points) != 1 else ''}")
    _titles(fig, ax, "Site layout (as supplied in the KML)",
            " · ".join(bits) + f" · grid: {an.utm_epsg} (UTM), km from frame corner")
    _footer(fig, stamp)
    _save(fig, path)


# ---------------------------------------------------------------------------
# 2. elevation
# ---------------------------------------------------------------------------
def _elev_norm(an: Analysis) -> Normalize:
    finite = an.dem.z[np.isfinite(an.dem.z)]
    lo, hi = np.percentile(finite, [0.5, 99.5])
    if hi - lo < ELEV_MIN_SPAN_M:
        mid = (hi + lo) / 2
        lo, hi = mid - ELEV_MIN_SPAN_M / 2, mid + ELEV_MIN_SPAN_M / 2
    return Normalize(vmin=float(lo), vmax=float(hi), clip=True)


def draw_elevation(an: Analysis, path: Path, stamp: str, dem_name: str) -> None:
    frame = _Frame(an)
    fig = _map_figure(frame, 1.3)
    ax = _map_axes(fig, frame, an.utm_epsg)
    nan = ~np.isfinite(an.dem.z)
    norm = _elev_norm(an)
    rgb = ELEV_CMAP(norm(an.z_filled))[..., :3]
    ls = LightSource(azdeg=315, altdeg=45)
    # LightSource assumes row 0 is the northern edge; our grid runs south -> north.
    hs = ls.hillshade(an.z_filled[::-1], vert_exag=HILLSHADE_EXAG, dx=an.dx_m, dy=an.dy_m)[::-1]
    shaded = ls.blend_soft_light(rgb, hs[..., None])
    shaded[nan] = NODATA_RGB
    ax.pcolormesh(frame.Xe, frame.Ye, np.clip(shaded, 0, 1), shading="flat", rasterized=True,
                  zorder=1)

    ci = an.contour_interval_m
    z = np.ma.masked_invalid(an.dem.z)
    zmin, zmax = float(z.min()), float(z.max())
    levels = np.arange(math.ceil(zmin / ci) * ci, zmax + 1e-9, ci)
    if levels.size:
        cs = ax.contour(frame.Xc, frame.Yc, z, levels=levels, colors=NAVY, linewidths=0.6,
                        alpha=0.75, zorder=3)
        step = max(1, len(levels) // 12)        # label at most ~12 levels
        ax.clabel(cs, levels=levels[::step], fmt=lambda v: f"{v:g}", fontsize=6.5,
                  inline=True, inline_spacing=2)
    _draw_outlines(ax, frame, an)
    _draw_routes_points(ax, frame, an, labels=False)
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap=ELEV_CMAP), ax=ax, shrink=0.9, pad=0.02,
                      extend="both")
    cb.set_label(f"Elevation (m above {an.dem.info.get('vertical_datum', 'datum')})",
                 fontsize=8.5, color=INK_MUTED)
    cb.ax.tick_params(labelsize=8, colors=INK_MUTED)
    _north_arrow(ax)
    _scale_bar(ax, frame)
    site_vals = [v for s in an.sites for v in (s.elev_min, s.elev_max) if math.isfinite(v)]
    lo_s, hi_s = (f"{min(site_vals):,.0f}", f"{max(site_vals):,.0f}") if site_vals else ("", "")
    rng = (f"site elevation {lo_s} m · " if lo_s == hi_s else f"site elevation {lo_s}–{hi_s} m · ")
    rng = rng if site_vals else ""
    contours = f"contours every {ci:g} m" if levels.size else f"no {ci:g} m contour crosses the frame"
    surface = "DSM" in str(an.dem.info.get("model_type", ""))
    _titles(fig, ax, f"Elevation — {_mpl(dem_name)}{' (surface model)' if surface else ''}",
            f"{rng}{contours} · hillshade from the north-west · site outlines in navy")
    _footer(fig, stamp)
    _save(fig, path)


# ---------------------------------------------------------------------------
# 3. slope classes
# ---------------------------------------------------------------------------
def draw_slope_classes(an: Analysis, path: Path, stamp: str) -> None:
    frame = _Frame(an)
    fig = _map_figure(frame, 2.6)
    ax = _map_axes(fig, frame, an.utm_epsg)
    colours = np.array([to_rgb(c) for c in SLOPE_COLOURS])
    edges = [b[1] for b in SLOPE_BINS[1:]]                       # 2, 5, 10, 15, 25, 35
    nan = ~np.isfinite(an.slope)
    idx = np.digitize(np.where(nan, 0, an.slope), edges)
    rgb = colours[idx]
    if an.sites:
        # Buffer cells give context but are not counted: draw them as a light grey ramp.
        outside = ~an.site_mask
        rgb[outside] = BUFFER_GREYS[idx[outside]]
    rgb[nan] = NODATA_RGB
    ax.pcolormesh(frame.Xe, frame.Ye, rgb, shading="flat", rasterized=True, zorder=1)
    _draw_outlines(ax, frame, an)
    _draw_routes_points(ax, frame, an, labels=False)
    _north_arrow(ax)
    _scale_bar(ax, frame)

    # Legend grouped by KPKT class so the 15/25/35° class boundaries are explicit.
    bins = an.bins_overall or {}
    handles, labels, headers = [], [], []
    for header, members in KPKT_GROUPS:
        headers.append(len(labels))
        handles.append(Patch(visible=False))
        labels.append(header)
        for i in members:
            pct = bins.get(SLOPE_BINS[i][0])
            pct_s = f"{pct:5.1f}%" if pct is not None and math.isfinite(pct) else "  n/a"
            handles.append(Patch(facecolor=SLOPE_COLOURS[i], edgecolor=GRID, lw=0.6))
            labels.append(f"{SLOPE_LABELS[i]:<7} {pct_s}" if an.sites else SLOPE_LABELS[i])
    if an.sites:
        handles.append(Patch(facecolor=BUFFER_GREYS[2], edgecolor=GRID))
        labels.append("outside sites (not counted)")
    if nan.any():
        handles.append(Patch(facecolor=NODATA_RGB, edgecolor=GRID))
        labels.append("no DEM data")
    leg = ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(1.02, 1.0),
                    fontsize=8, frameon=False,
                    title="Slope · % of site area" if an.sites else "Slope",
                    title_fontsize=8.5, handlelength=1.6, borderaxespad=0)
    leg.get_title().set_color(NAVY)
    leg.get_title().set_fontweight("bold")
    for k, text in enumerate(leg.get_texts()):
        text.set_color(NAVY if k in headers else INK_MUTED)
        if k in headers:
            text.set_fontweight("bold")
            text.set_fontsize(8)
        else:
            text.set_family("monospace")

    class_i = an.kpkt_overall.get("I")
    if class_i is not None and math.isfinite(class_i):
        title = f"Slope classes — by slope, {class_i:.1f}% of site area is KPKT Class I (< 15°)"
    else:
        title = "Slope classes (KPKT, by slope only)"
    scope = ("Statistics count DEM cells inside the site boundaries only (grey: buffer)"
             if an.sites else "No site polygon supplied: slope shown for the whole frame")
    _titles(fig, ax, title, f"{scope} · grid ≈ {an.grid_spacing_m:.0f} m, short steep "
                            "features are smoothed out")
    _footer(fig, stamp)
    _save(fig, path)


# ---------------------------------------------------------------------------
# 4. profiles
# ---------------------------------------------------------------------------
def _runs(mask: np.ndarray):
    """(start, end) index pairs of contiguous True runs."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0] - 1))


def _profile_panel(ax, dist_m, elev, title: str, inside=None, colour=NAVY) -> None:
    km = dist_m / 1000.0
    ok = np.isfinite(elev)
    ax.set_title(title, loc="left", fontsize=9, color=NAVY, fontweight="bold")
    ax.set_facecolor("white")
    ax.grid(color=GRID, lw=0.6)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(labelsize=8, colors=INK_MUTED)
    ax.set_ylabel("Elevation (m)", fontsize=8, color=INK_MUTED)
    if not ok.any():
        ax.text(0.5, 0.5, "No DEM data along this line", transform=ax.transAxes,
                ha="center", va="center", fontsize=9, color=INK_MUTED)
        return
    lo, hi = float(np.nanmin(elev)), float(np.nanmax(elev))
    if hi - lo < PROFILE_MIN_SPAN_M:
        mid = (hi + lo) / 2
        lo, hi = mid - PROFILE_MIN_SPAN_M / 2, mid + PROFILE_MIN_SPAN_M / 2
    pad = 0.08 * (hi - lo)
    base = lo - pad
    if inside is not None:
        for a, b in _runs(inside):
            x0 = km[max(a - 1, 0)] if a else km[0]
            ax.axvspan((km[a] + x0) / 2 if a else km[0],
                       (km[b] + km[min(b + 1, km.size - 1)]) / 2, color=GOLD, alpha=0.22, lw=0,
                       zorder=0)
    ax.fill_between(km, np.where(ok, elev, np.nan), base, color=PAPER, zorder=1)
    ax.plot(km, elev, color=colour, lw=1.6, zorder=2)
    ax.set_ylim(base, hi + pad)
    ax.set_xlim(km[0], km[-1])


def draw_profiles(an: Analysis, path: Path, stamp: str) -> None:
    routes = an.routes[:MAX_ROUTE_PANELS]
    rows = 2 + len(routes)
    fig = _new_figure((10.0, 1.2 + 2.35 * rows))
    axes = fig.subplots(rows, 1, squeeze=False)[:, 0]
    names = {"W-E": "West → East", "S-N": "South → North"}
    for ax, t in zip(axes[:2], an.transects):
        through = f" through {_mpl(_short(t.through, 40))}" if t.through else " through the features"
        _profile_panel(ax, t.dist_m, t.elev, f"{names[t.direction]}{through}",
                       inside=t.inside if an.sites else None)
        ax.set_xlabel(f"Distance from {'west' if t.direction == 'W-E' else 'south'} edge "
                      "of frame (km)", fontsize=8, color=INK_MUTED)
    for ax, r in zip(axes[2:], routes):
        grade = f"{r.max_grade_pct:.1f}%" if math.isfinite(r.max_grade_pct) else "n/a"
        _profile_panel(ax, r.dist_m, r.elev,
                       f"Route — {_mpl(_short(r.name, 40))} · {r.length_m / 1000:,.2f} km · "
                       f"max grade {grade}", colour=NAVY)
        ax.set_xlabel("Distance along route from first vertex (km)", fontsize=8, color=INK_MUTED)
    if an.sites:
        axes[0].legend(handles=[Patch(facecolor=GOLD, alpha=0.3, label="inside site boundary")],
                       loc="upper right", fontsize=7.5, frameon=False)
    extra = len(an.routes) - len(routes)
    more = f" · {extra} more route{'s' if extra != 1 else ''} not shown" if extra > 0 else ""
    fig.suptitle("Terrain profiles", x=0.02, ha="left", fontsize=13, fontweight="bold",
                 color=NAVY)
    axes[0].set_title("Vertical scale exaggerated — not to scale" + more, loc="right",
                      fontsize=8, color=INK_MUTED)
    _footer(fig, stamp)
    _save(fig, path)


# ---------------------------------------------------------------------------
FIGURE_FILES = ("1_site_layout.png", "2_elevation.png", "3_slope_classes.png", "4_profiles.png")


def draw_all(an: Analysis, out_dir: Path, stamp: str) -> list[str]:
    """Draw the four figures into out_dir; returns the file names in order."""
    out_dir = Path(out_dir)
    draw_site_layout(an, out_dir / FIGURE_FILES[0], stamp)
    draw_elevation(an, out_dir / FIGURE_FILES[1], stamp, an.dem.info["name"])
    draw_slope_classes(an, out_dir / FIGURE_FILES[2], stamp)
    draw_profiles(an, out_dir / FIGURE_FILES[3], stamp)
    return list(FIGURE_FILES)
