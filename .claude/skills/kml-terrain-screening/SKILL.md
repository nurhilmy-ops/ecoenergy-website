---
name: kml-terrain-screening
description: >-
  Screening-grade terrain analysis for solar PV / floating solar (FPV) and other land
  development sites in Malaysia from a KML/KMZ file. Parses site polygons, cable/access
  routes and points; samples an open DEM (SRTM 30 m via OpenTopoData); and produces PNG
  outputs — site layout map, elevation heatmap with contours, KPKT slope classification
  map, and terrain cross-section profiles — plus a summary.md with areas, slope statistics,
  regulatory flags and recommended follow-up studies. Use this skill whenever the user
  provides a .kml or .kmz file, asks about terrain, topography, elevation, slope, contours
  or a terrain profile of a site, asks "is this land flat", wants a site screening or
  pre-feasibility terrain check, or mentions analysing land for a solar farm, FPV pond,
  or plant layout — even if they don't say "terrain" explicitly.
compatibility: >-
  Requires Python 3 with numpy, scipy, matplotlib, shapely, pyproj, requests
  (pip install if missing) and internet access to api.opentopodata.org.
---

# KML Terrain Screening (Malaysia solar/FPV site feasibility)

## What this skill does and why

A KML file almost never contains terrain data — it holds boundary polygons, routes and
placemarks. Users often believe the KML "shows the terrain"; it does not. This skill
derives the terrain by overlaying an open ~30 m DEM on the KML geometry, then reports
what a Malaysian solar consultant needs at pre-feasibility stage: areas, elevation
range, slope classes, profiles, and the follow-up studies the findings trigger.

Everything produced is **screening-grade**. Make that limitation explicit in every
output: SRTM vertical accuracy is roughly ±5–10 m in vegetated tropical terrain (radar
partly measures canopy, not ground), and the sampling grid is ~80 m. It is good enough
to classify landform and slope and to route a cable line; it is NOT a substitute for a
licensed land surveyor's topo survey (Licensed Land Surveyors Act 1958) or for
earthworks/drainage design to MSMA 2nd Edition.

## Workflow

1. **Run the pipeline script** (does everything in one pass):

   ```bash
   pip install numpy scipy matplotlib shapely pyproj requests --quiet
   python scripts/terrain_screen.py "<input.kml>" --out <output_dir>
   ```

   For .kmz: unzip first (`unzip -o file.kmz -d /tmp/kmz && mv /tmp/kmz/doc.kml input.kml`).

   The script parses all Polygons / LineStrings / Points, computes geodesic areas and
   lengths, builds a lat/lon sample grid over the polygon extents (+~130 m buffer,
   auto-spaced to stay under ~800 API points), fetches elevations from OpenTopoData
   (`srtm30m`, max 100 locations per request, 1 request/second — the script batches and
   throttles automatically), then writes the four PNGs and `summary.md`.

2. **Read `summary.md` and the printed stats**, then verify the outputs by viewing the
   PNGs before presenting them. Check especially: polygons plot inside the frame,
   slope percentages are consistent, profiles are not flat-zero (a sign of failed fetch).

3. **Open every land description with the key location snapshot.** In any conceptual
   study, pre-feasibility report or chat answer that describes the land, the FIRST
   thing stated must be the key location snapshot of the KML site (the script computes
   it and writes it at the top of `summary.md`; it is also printed to stdout and
   stamped on the layout-map title):

   - **Where it is**: site centroid coordinates (area-weighted across all parcels).
   - **With respect to the overall project size**: number of parcels, total area in
     ha (and km²), and the overall E–W × N–S extent in km.
   - **With respect to the nearest major city**: straight-line distance and compass
     direction from the nearest major Malaysian city (gazetteer of state capitals +
     Singapore built into the script), with the second-nearest for context — e.g.
     "≈ 32 km NE of Ipoh, Perak". Always caveat that these are geodesic, not road,
     distances.

   Only after this snapshot may the write-up move on to terrain, slope, flags and
   follow-ups. Never open a land-matter section with geometry tables or slope
   statistics.

4. **Interpret for the user.** Read `references/malaysia-context.md` for the KPKT slope
   classes, EIA thresholds, FPV-specific checks (SRTM epoch vs pond excavation date,
   bathymetry needs), and the standard JMG / MET Malaysia / 1-5-10 km EIA-SIA follow-up
   list. Present findings critically — flag contradictions (e.g. "floating" sites whose
   DEM shows undulating land) rather than glossing over them.

## Outputs (all PNG + one markdown, no Word documents unless asked)

| File | Content |
|---|---|
| `1_site_layout.png` | All polygons with name + ha labels, routes with length, points; UTM axes, north arrow |
| `2_elevation_heatmap.png` | Interpolated elevation surface, 2 m contours, site boundaries overlaid |
| `3_slope_classification.png` | Slope in degrees binned 0–2/2–5/5–10/10–15/15–25/>25°, KPKT class note in title |
| `4_terrain_profiles.png` | W–E and S–N transects through the largest site + a profile along each LineString route |
| `summary.md` | Opens with the key location snapshot (centroid, project size/extent, distance & bearing from nearest major city), then areas, perimeter, elevation/slope stats, KPKT class split, flags, follow-up studies |

Keep titles honest: label the DEM source, resolution and "screening grade" on the
figures themselves, so the images stay self-caveating when forwarded.

## Failure modes and fallbacks

- **OpenTopoData unreachable / rate-limited (HTTP 429)**: the script retries once per
  batch after a 5 s wait. If the environment blocks the domain entirely, tell the user
  plainly and offer two options: (a) they supply a GeoTIFF/XYZ export of the area
  (e.g. from OpenTopography or JUPEM) which the script accepts via `--geotiff`, or
  (b) reduce ambition to geometry-only outputs (layout map + areas, no elevation).
  Do not silently fabricate elevations.
- **Polygon with altitude values in KML**: ignore the z values — Google Earth writes
  them inconsistently and drapes geometry onto its own terrain anyway.
- **Sites larger than ~10 km across**: increase `--max-points` (each 100 points ≈ 1 s
  of fetch time) rather than accepting a very coarse grid.
- **Null elevations returned** (offshore/void cells): the script masks them; if >10% of
  the grid is null, warn the user the site may be outside SRTM coverage (>60°N/S) or
  over open sea.

## Critical-consultant behaviours (always apply)

- State the SRTM acquisition epoch (Feb 2000) when the site is a water body: ponds
  excavated after 2000 will show as land in the DEM. For FPV, terrain is secondary —
  bathymetry, water-level fluctuation and bund integrity govern the design, and no DEM
  provides those. Say so.
- Compare total polygon area against the EIA threshold discussion in
  `references/malaysia-context.md` and flag accordingly — do not assert a threshold
  from memory without checking the reference.
- Recommend, as standard follow-ups: JMG geological sheet lookup, MET Malaysia climate
  data from the nearest station, and the 1 km / 5 km / 10 km surrounding-activity scan
  for EIA/SIA context.
