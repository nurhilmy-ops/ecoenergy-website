#!/usr/bin/env python3
"""KML terrain screening pipeline (screening-grade, SRTM 30 m).

Parses a KML, samples an open DEM over the polygon extents, and writes:
  1_site_layout.png, 2_elevation_heatmap.png, 3_slope_classification.png,
  4_terrain_profiles.png, summary.md

Usage:
  python terrain_screen.py input.kml --out ./screening [--dataset srtm30m]
      [--max-points 800] [--buffer-deg 0.0012] [--geotiff dem.tif]
"""
import argparse, json, math, sys, time
import xml.etree.ElementTree as ET

import numpy as np
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Polygon as MplPoly
from scipy.interpolate import RectBivariateSpline
from shapely.geometry import Polygon, LineString
from pyproj import Transformer, Geod

KMLNS = "{http://www.opengis.net/kml/2.2}"
API = "https://api.opentopodata.org/v1/{dataset}"
GEOD = Geod(ellps="WGS84")

# Gazetteer for the key location snapshot: Malaysian state capitals / major cities
# (plus Singapore, relevant for Johor sites). (name, state, lat, lon)
MAJOR_CITIES = [
    ("Kuala Lumpur", "Federal Territory", 3.1390, 101.6869),
    ("George Town", "Penang", 5.4141, 100.3288),
    ("Ipoh", "Perak", 4.5975, 101.0901),
    ("Shah Alam", "Selangor", 3.0733, 101.5185),
    ("Putrajaya", "Federal Territory", 2.9264, 101.6964),
    ("Seremban", "Negeri Sembilan", 2.7297, 101.9381),
    ("Malacca City", "Melaka", 2.1896, 102.2501),
    ("Johor Bahru", "Johor", 1.4927, 103.7414),
    ("Kuantan", "Pahang", 3.8077, 103.3260),
    ("Kuala Terengganu", "Terengganu", 5.3302, 103.1408),
    ("Kota Bharu", "Kelantan", 6.1254, 102.2381),
    ("Alor Setar", "Kedah", 6.1248, 100.3678),
    ("Kangar", "Perlis", 6.4414, 100.1986),
    ("Kota Kinabalu", "Sabah", 5.9804, 116.0735),
    ("Sandakan", "Sabah", 5.8394, 118.1172),
    ("Tawau", "Sabah", 4.2448, 117.8911),
    ("Kuching", "Sarawak", 1.5533, 110.3592),
    ("Sibu", "Sarawak", 2.2870, 111.8305),
    ("Bintulu", "Sarawak", 3.1714, 113.0419),
    ("Miri", "Sarawak", 4.3995, 113.9914),
    ("Singapore", "Singapore", 1.3521, 103.8198),
]

COMPASS16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def location_snapshot(feats):
    """Key location snapshot: overall centroid, project size/extent, and the
    site's position relative to the two nearest major cities (geodesic)."""
    polys = [f for f in feats if f["type"] == "polygon" and f.get("area_ha", 0) > 0]
    if polys:  # area-weighted centroid across all parcels
        tot = sum(f["area_ha"] for f in polys)
        lon = sum(f["centroid"][0] * f["area_ha"] for f in polys) / tot
        lat = sum(f["centroid"][1] * f["area_ha"] for f in polys) / tot
    else:
        pts = [p for f in feats for p in f["coords"]]
        lon = sum(p[0] for p in pts) / len(pts)
        lat = sum(p[1] for p in pts) / len(pts)
        tot = 0.0
    pts = [p for f in feats for p in f["coords"]]
    lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
    _, _, ew = GEOD.inv(min(lons), lat, max(lons), lat)
    _, _, ns = GEOD.inv(lon, min(lats), lon, max(lats))
    ranked = []
    for name, state, clat, clon in MAJOR_CITIES:
        az, _, dist = GEOD.inv(clon, clat, lon, lat)  # azimuth city -> site
        ranked.append((dist / 1e3, COMPASS16[round((az % 360) / 22.5) % 16],
                       name, state))
    ranked.sort()
    return {"lat": lat, "lon": lon, "total_ha": tot, "n_parcels": len(polys),
            "ew_km": ew / 1e3, "ns_km": ns / 1e3, "cities": ranked[:2]}


def snapshot_md(s):
    d1, dir1, city1, state1 = s["cities"][0]
    d2, dir2, city2, state2 = s["cities"][1]
    lat_h = "N" if s["lat"] >= 0 else "S"; lon_h = "E" if s["lon"] >= 0 else "W"
    return (
        "## Key location snapshot\n\n"
        f"- **Site centroid**: {abs(s['lat']):.5f}° {lat_h}, "
        f"{abs(s['lon']):.5f}° {lon_h}\n"
        f"- **Overall project size**: {s['n_parcels']} parcel(s) totalling "
        f"{s['total_ha']:.1f} ha ({s['total_ha']/100:.2f} km²), overall extent "
        f"≈ {s['ew_km']:.1f} km E–W × {s['ns_km']:.1f} km N–S\n"
        f"- **Nearest major city**: ≈ {d1:.0f} km {dir1} of {city1}, {state1} "
        f"(straight-line); next nearest {city2}, {state2} ≈ {d2:.0f} km\n"
        "- Distances are geodesic (straight-line), not road distances.\n\n")


def parse_kml(path):
    root = ET.parse(path).getroot()
    feats = []
    for pm in root.iter(KMLNS + "Placemark"):
        name_el = pm.find(KMLNS + "name")
        name = name_el.text.strip() if name_el is not None and name_el.text else "unnamed"
        for tag, gtype in [("Polygon", "polygon"), ("LineString", "line"), ("Point", "point")]:
            for g in pm.iter(KMLNS + tag):
                c = g.find(".//" + KMLNS + "coordinates")
                if c is None or not c.text:
                    continue
                pts = []
                for tok in c.text.split():
                    p = tok.split(",")
                    pts.append((float(p[0]), float(p[1])))  # ignore z: unreliable in KML
                f = {"name": name, "type": gtype, "coords": pts}
                if gtype == "polygon" and len(pts) >= 3:
                    area, perim = GEOD.geometry_area_perimeter(Polygon(pts))
                    f["area_ha"] = abs(area) / 1e4
                    f["perimeter_m"] = abs(perim)
                    cen = Polygon(pts).centroid
                    f["centroid"] = (cen.x, cen.y)
                elif gtype == "line" and len(pts) >= 2:
                    f["length_m"] = GEOD.geometry_length(LineString(pts))
                feats.append(f)
    if not feats:
        sys.exit("No geometry found in KML.")
    return feats


def utm_epsg(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


def build_grid(feats, buffer_deg, max_points):
    polys = [f for f in feats if f["type"] == "polygon" and f.get("area_ha", 0) > 0.5]
    if not polys:  # fall back to everything
        polys = feats
    pts = [p for f in polys for p in f["coords"]]
    lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
    lon0, lon1 = min(lons) - buffer_deg, max(lons) + buffer_deg
    lat0, lat1 = min(lats) - buffer_deg, max(lats) + buffer_deg
    # choose spacing so n_lat*n_lon <= max_points, min ~0.0003 deg (~33 m)
    span = max(lon1 - lon0, 1e-4) * max(lat1 - lat0, 1e-4)
    spacing = max(3e-4, math.sqrt(span / max_points))
    glons = np.arange(lon0, lon1, spacing)
    glats = np.arange(lat0, lat1, spacing)
    return glats, glons


def fetch_elevations(latlons, dataset, session):
    """Batch (100/req, 1 req/s per OpenTopoData public limits). Returns list w/ None."""
    out = []
    for i in range(0, len(latlons), 100):
        chunk = latlons[i:i + 100]
        loc = "|".join(f"{la:.5f},{lo:.5f}" for la, lo in chunk)
        url = API.format(dataset=dataset) + "?locations=" + loc
        for attempt in (1, 2):
            try:
                r = session.get(url, timeout=30)
                if r.status_code == 429:
                    time.sleep(5); continue
                r.raise_for_status()
                j = r.json()
                if j.get("status") != "OK":
                    raise RuntimeError(j)
                out.extend([res["elevation"] for res in j["results"]])
                break
            except Exception as e:
                if attempt == 2:
                    raise SystemExit(f"DEM fetch failed at batch {i//100}: {e}\n"
                                     "If this environment blocks api.opentopodata.org, "
                                     "supply a GeoTIFF with --geotiff instead.")
                time.sleep(5)
        time.sleep(1.05)
        print(f"  fetched {min(i+100,len(latlons))}/{len(latlons)} points", flush=True)
    return out


def sample_geotiff(path, latlons):
    try:
        import rasterio
    except ImportError:
        sys.exit("--geotiff requires rasterio (pip install rasterio)")
    with rasterio.open(path) as src:
        vals = [v[0] if v[0] != src.nodata else None
                for v in src.sample([(lo, la) for la, lo in latlons])]
    return [float(v) if v is not None else None for v in vals]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kml")
    ap.add_argument("--out", default="./screening")
    ap.add_argument("--dataset", default="srtm30m")
    ap.add_argument("--max-points", type=int, default=800)
    ap.add_argument("--buffer-deg", type=float, default=0.0012)
    ap.add_argument("--geotiff", default=None)
    a = ap.parse_args()

    import os
    os.makedirs(a.out, exist_ok=True)
    feats = parse_kml(a.kml)
    polys = [f for f in feats if f["type"] == "polygon"]
    lines = [f for f in feats if f["type"] == "line"]
    points = [f for f in feats if f["type"] == "point"]
    print("Features:", [(f["name"], f["type"]) for f in feats])
    snap = location_snapshot(feats)
    d1, dir1, city1, state1 = snap["cities"][0]
    print(f"Location: {snap['lat']:.5f}, {snap['lon']:.5f} — "
          f"~{d1:.0f} km {dir1} of {city1}, {state1}")

    glats, glons = build_grid(feats, a.buffer_deg, a.max_points)
    grid_ll = [(la, lo) for la in glats for lo in glons]
    # route samples: ~90 per line
    route_samples = {}
    for f in lines:
        ls = LineString(f["coords"])
        n = min(90, max(30, int(f["length_m"] / 50)))
        rp = [ls.interpolate(d, normalized=True) for d in np.linspace(0, 1, n)]
        route_samples[f["name"]] = [(p.x, p.y) for p in rp]
    route_ll = [(p[1], p[0]) for f in lines for p in route_samples[f["name"]]]

    all_ll = grid_ll + route_ll
    print(f"Sampling DEM: {len(grid_ll)} grid + {len(route_ll)} route points "
          f"({math.ceil(len(all_ll)/100)} requests, ~{math.ceil(len(all_ll)/100)}s)")
    if a.geotiff:
        elev = sample_geotiff(a.geotiff, all_ll)
        src_label = f"user GeoTIFF ({a.geotiff})"
    else:
        elev = fetch_elevations(all_ll, a.dataset, requests.Session())
        src_label = f"{a.dataset.upper()} via OpenTopoData (~30 m, screening grade)"

    ge = np.array([np.nan if v is None else v for v in elev[:len(grid_ll)]],
                  dtype=float).reshape(len(glats), len(glons))
    nan_pct = 100 * np.isnan(ge).mean()
    if nan_pct > 10:
        print(f"WARNING: {nan_pct:.0f}% of grid has no DEM value.")
    if np.isnan(ge).any():
        med = np.nanmedian(ge)
        ge = np.where(np.isnan(ge), med, ge)

    # metric coordinates
    lon_c = float(np.mean(glons)); lat_c = float(np.mean(glats))
    T = Transformer.from_crs("EPSG:4326", utm_epsg(lon_c, lat_c), always_xy=True)
    x_m = np.array(T.transform(glons, np.full_like(glons, lat_c))[0])
    y_m = np.array(T.transform(np.full_like(glats, lon_c), glats)[1])
    x0, y0 = x_m.min(), y_m.min()

    def poly_xy(f):
        xs, ys = T.transform([p[0] for p in f["coords"]], [p[1] for p in f["coords"]])
        return (np.array(xs) - x0) / 1e3, (np.array(ys) - y0) / 1e3

    # slope (degrees) on the raw grid
    dy = float(np.mean(np.diff(y_m))); dx = float(np.mean(np.diff(x_m)))
    gy, gx = np.gradient(ge, dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    kpkt = {"Class I (<15°)": float(100 * np.mean(slope < 15)),
            "Class II (15–25°)": float(100 * np.mean((slope >= 15) & (slope < 25))),
            "Class III (25–35°)": float(100 * np.mean((slope >= 25) & (slope < 35))),
            "Class IV (>35°)": float(100 * np.mean(slope >= 35))}

    # smooth surface for display/profiles
    spl = RectBivariateSpline(y_m, x_m, ge, kx=3, ky=3, s=ge.size * 1.5)
    xf = np.linspace(x_m.min(), x_m.max(), 180)
    yf = np.linspace(y_m.min(), y_m.max(), 220)
    Zf = spl(yf, xf); XF, YF = np.meshgrid((xf - x0) / 1e3, (yf - y0) / 1e3)

    cyc = plt.cm.tab10.colors

    # ---- fig 1: layout ----
    fig, ax = plt.subplots(figsize=(9, 9))
    for i, f in enumerate(lines):
        px, py = poly_xy(f)
        ax.plot(px, py, ls="--", lw=2.2, color="#ff8c00",
                label=f"{f['name']} ({f['length_m']/1e3:.2f} km)")
    for i, f in enumerate(polys):
        px, py = poly_xy(f); c = cyc[i % 10]
        ax.add_patch(MplPoly(np.c_[px, py], closed=True, facecolor=c, alpha=0.35,
                             edgecolor=c, lw=2))
        if f.get("area_ha", 0) > 0.5:
            cx, cy = T.transform([f["centroid"][0]], [f["centroid"][1]])
            ax.text((cx[0]-x0)/1e3, (cy[0]-y0)/1e3, f"{f['name']}\n{f['area_ha']:.1f} ha",
                    ha="center", va="center", fontsize=10, fontweight="bold")
    for f in points:
        px, py = T.transform([f["coords"][0][0]], [f["coords"][0][1]])
        ax.plot((px[0]-x0)/1e3, (py[0]-y0)/1e3, "k^", ms=10)
        ax.annotate(f["name"], ((px[0]-x0)/1e3, (py[0]-y0)/1e3),
                    textcoords="offset points", xytext=(8, 6), fontsize=8)
    tot = sum(f.get("area_ha", 0) for f in polys)
    ax.set_title(f"Site Layout (from KML) — total polygon area {tot:.1f} ha\n"
                 f"≈ {d1:.0f} km {dir1} of {city1}, {state1} | "
                 f"CRS: WGS84 / {utm_epsg(lon_c, lat_c)}", fontsize=12)
    ax.set_xlabel("Easting (km, local)"); ax.set_ylabel("Northing (km, local)")
    ax.set_aspect("equal"); ax.grid(alpha=0.3); ax.legend(loc="best", fontsize=8)
    ax.annotate("N", xy=(0.05, 0.95), xycoords="axes fraction", fontsize=14,
                fontweight="bold", ha="center")
    ax.annotate("", xy=(0.05, 0.94), xytext=(0.05, 0.87), xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", lw=2))
    plt.tight_layout(); plt.savefig(f"{a.out}/1_site_layout.png", dpi=150); plt.close()

    # ---- fig 2: elevation ----
    fig, ax = plt.subplots(figsize=(9, 9))
    pc = ax.pcolormesh(XF, YF, Zf, cmap="terrain", shading="auto")
    lo, hi = np.floor(ge.min()), np.ceil(ge.max())
    step = max(1, round((hi - lo) / 12))
    cs = ax.contour(XF, YF, Zf, levels=np.arange(lo, hi, step), colors="k",
                    linewidths=0.4, alpha=0.6)
    ax.clabel(cs, fmt="%d", fontsize=7)
    for f in polys:
        px, py = poly_xy(f)
        ax.plot(np.append(px, px[0]), np.append(py, py[0]), color="red", lw=2)
    plt.colorbar(pc, ax=ax, shrink=0.8, label=f"Elevation (m) — {src_label}")
    ax.set_title(f"Elevation Surface — {src_label}\ncontour interval {step} m | "
                 "vertical accuracy ±5–10 m in vegetated terrain", fontsize=11)
    ax.set_xlabel("Easting (km, local)"); ax.set_ylabel("Northing (km, local)")
    ax.set_aspect("equal")
    plt.tight_layout(); plt.savefig(f"{a.out}/2_elevation_heatmap.png", dpi=150); plt.close()

    # ---- fig 3: slope ----
    fig, ax = plt.subplots(figsize=(9, 9))
    bounds = [0, 2, 5, 10, 15, 25, 90]
    cmap = ListedColormap(["#1a9850", "#91cf60", "#d9ef8b", "#fee08b", "#fc8d59", "#d73027"])
    norm = BoundaryNorm(bounds, cmap.N)
    GX, GY = np.meshgrid((x_m - x0) / 1e3, (y_m - y0) / 1e3)
    pc = ax.pcolormesh(GX, GY, slope, cmap=cmap, norm=norm, shading="auto")
    for f in polys:
        px, py = poly_xy(f)
        ax.plot(np.append(px, px[0]), np.append(py, py[0]), color="k", lw=2)
    cb = plt.colorbar(pc, ax=ax, shrink=0.8, ticks=[1, 3.5, 7.5, 12.5, 20, 40])
    cb.ax.set_yticklabels(["0–2°", "2–5°", "5–10°", "10–15°", "15–25°", ">25°"])
    cb.set_label("Slope (degrees)")
    ax.set_title(f"Slope Classification — KPKT hillside classes\n"
                 f"{kpkt['Class I (<15°)']:.1f}% of analysed frame is Class I (<15°) | "
                 f"grid ≈ {abs(dx):.0f} m", fontsize=11)
    ax.set_xlabel("Easting (km, local)"); ax.set_ylabel("Northing (km, local)")
    ax.set_aspect("equal")
    plt.tight_layout(); plt.savefig(f"{a.out}/3_slope_classification.png", dpi=150); plt.close()

    # ---- fig 4: profiles ----
    n_rows = 2 + len(lines)
    fig, axs = plt.subplots(n_rows, 1, figsize=(11, 3.3 * n_rows))
    axs = np.atleast_1d(axs)
    big = max(polys, key=lambda f: f.get("area_ha", 0))
    cxy = T.transform([big["centroid"][0]], [big["centroid"][1]])
    prof_x = np.linspace(x_m.min(), x_m.max(), 200)
    zA = spl(np.full_like(prof_x, cxy[1][0]), prof_x, grid=False)
    axs[0].plot((prof_x - x0) / 1e3, zA, lw=2, color="#8b4513")
    axs[0].fill_between((prof_x - x0) / 1e3, zA, zA.min() - 1, color="#deb887", alpha=0.6)
    axs[0].set_title(f"Transect W→E through centroid of {big['name']}")
    prof_y = np.linspace(y_m.min(), y_m.max(), 200)
    zB = spl(prof_y, np.full_like(prof_y, cxy[0][0]), grid=False)
    axs[1].plot((prof_y - y0) / 1e3, zB, lw=2, color="#2f4f4f")
    axs[1].fill_between((prof_y - y0) / 1e3, zB, zB.min() - 1, color="#a9c9c9", alpha=0.6)
    axs[1].set_title(f"Transect S→N through centroid of {big['name']}")
    ri = len(grid_ll)
    for k, f in enumerate(lines):
        rp = route_samples[f["name"]]
        re_ = np.array([np.nan if v is None else v for v in elev[ri:ri + len(rp)]], float)
        ri += len(rp)
        d = [0.0]
        for i in range(1, len(rp)):
            _, _, dd = GEOD.inv(rp[i-1][0], rp[i-1][1], rp[i][0], rp[i][1])
            d.append(d[-1] + dd)
        d = np.array(d) / 1e3
        axs[2 + k].plot(d, re_, lw=2, color="#ff8c00")
        axs[2 + k].fill_between(d, re_, np.nanmin(re_) - 1, color="#ffd9a0", alpha=0.7)
        axs[2 + k].set_title(f"Route profile — {f['name']} ({f['length_m']/1e3:.2f} km)")
    for axx in axs:
        axx.set_ylabel("Elevation (m)"); axx.grid(alpha=0.3)
    axs[-1].set_xlabel("Distance (km)")
    fig.suptitle(f"Terrain Profiles — {src_label}", fontsize=12)
    plt.tight_layout(); plt.savefig(f"{a.out}/4_terrain_profiles.png", dpi=150); plt.close()

    # ---- summary.md ----
    with open(f"{a.out}/summary.md", "w") as fh:
        fh.write(f"# Terrain Screening Summary\n\nSource KML: `{a.kml}`\n"
                 f"DEM: {src_label} | Acquisition epoch for SRTM: Feb 2000\n\n")
        fh.write(snapshot_md(snap))
        fh.write("## Geometry\n\n")
        fh.write("| Feature | Type | Area (ha) / Length (km) |\n|---|---|---|\n")
        for f in feats:
            q = (f"{f['area_ha']:.2f} ha" if f["type"] == "polygon" and "area_ha" in f
                 else f"{f['length_m']/1e3:.2f} km" if f["type"] == "line" else "—")
            fh.write(f"| {f['name']} | {f['type']} | {q} |\n")
        fh.write(f"\n**Total polygon area: {tot:.1f} ha**\n\n## Terrain statistics "
                 f"(analysed frame incl. buffer)\n\n"
                 f"- Elevation: {ge.min():.0f}–{ge.max():.0f} m (mean {ge.mean():.1f} m)\n"
                 f"- Max slope: {slope.max():.1f}°; grid spacing ≈ {abs(dx):.0f} m\n")
        for k, v in kpkt.items():
            fh.write(f"- {k}: {v:.1f}%\n")
        fh.write("\n## Flags & caveats\n\n"
                 "- Screening grade only: SRTM ±5–10 m vertical in vegetated terrain; "
                 "not for earthworks/drainage design (MSMA 2nd Ed.) or submissions — "
                 "licensed topo survey required (Licensed Land Surveyors Act 1958).\n"
                 "- If sites are water bodies (FPV): SRTM predates ponds dug after 2000; "
                 "verify open-water extent on current imagery; bathymetry + water-level "
                 "records govern FPV design, not the DEM.\n"
                 "- Check total area against EIA Order 2015 prescribed-activity "
                 "thresholds (verify current schedule before advising).\n\n"
                 "## Recommended follow-up studies\n\n"
                 "1. JMG geological sheet for the site (foundations/anchors).\n"
                 "2. MET Malaysia climate normals from the nearest station.\n"
                 "3. 1 km / 5 km / 10 km surrounding-activity scan for EIA/SIA.\n"
                 "4. Licensed topo survey or LiDAR/drone photogrammetry at design stage.\n"
                 "5. For FPV: bathymetric survey and seasonal water-level records.\n")
    print("Wrote outputs to", a.out)
    print("KPKT:", {k: round(v, 1) for k, v in kpkt.items()})


if __name__ == "__main__":
    main()
