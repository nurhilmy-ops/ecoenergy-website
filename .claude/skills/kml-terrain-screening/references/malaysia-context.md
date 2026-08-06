# Malaysia context for terrain screening interpretation

Read this when interpreting outputs for the user. Where regulations are cited, verify
the current version with a web search before advising — thresholds and guidelines get
amended.

## Slope classification (KPKT)

The Garis Panduan Pembangunan di Kawasan Bukit dan Tanah Tinggi (KPKT — Ministry of
Housing and Local Government hillside development guidelines) uses four classes:

| Class | Slope | Typical planning consequence |
|---|---|---|
| I | < 15° | Generally developable |
| II | 15–25° | Development with engineering controls |
| III | 25–35° | Restricted; geotechnical report typically required |
| IV | > 35° | Generally no development |

State/local authorities (e.g. under each Rancangan Tempatan) may apply stricter local
rules — check the relevant PBT/local council guideline for the site's district.

Note the measurement scale: slope from an ~80 m DEM sample grid underestimates local
slopes. Report the class split with that caveat.

## EIA / land thresholds

Prescribed activities are listed in the Environmental Quality (Prescribed Activities)
(Environmental Impact Assessment) Order 2015 (as amended) under the Environmental
Quality Act 1974. Land-clearing area and certain energy-infrastructure categories can
trigger a DOE EIA. Do not quote a hectare threshold from memory — check the current
First/Second Schedule (DOE Malaysia website) against the computed site area, and note
whether the site involves hill land, forest, or conversion of agricultural land, which
changes the analysis.

For the EIA/SIA context scan, identify activities within 1 km, 5 km and 10 km radii of
the site (settlements, schools, rivers/intakes, forest reserves, industry, mining) and
remark on each.

## Standard data sources

- **Geology**: JMG (Jabatan Mineral dan Geosains) published geological sheet maps —
  identify formation, lithology, and any karst/ex-mining ground.
- **Weather**: MET Malaysia (Jabatan Meteorologi) climate normals from the nearest
  station — rainfall intensity feeds MSMA drainage thinking; wind for structures
  (MS 1553 for wind loading).
- **Drainage/stormwater design standard**: MSMA 2nd Edition (DID/JPS, 2012) — design
  stage, not screening.
- **Survey**: design-grade topo requires a licensed land surveyor (Licensed Land
  Surveyors Act 1958) or LiDAR/drone photogrammetry with ground control.

## DEM limitations (say these out loud in the deliverable)

- SRTM 1-arc-second was acquired in **February 2000**. Ponds, cuts, platforms and
  buildings created after 2000 do not exist in it.
- Vertical accuracy in vegetated tropical terrain is ±5–10 m; C-band radar partially
  returns from the canopy, so forested/oil-palm areas read high.
- 30 m posting smooths away bunds, small streams and minor cut slopes.
- Alternative open DEMs if better data is needed at screening stage: Copernicus GLO-30
  (usually better than SRTM), or ask the user for JUPEM/IFSAR products if licensed.

## FPV-specific checks

Terrain is secondary for floating solar. The governing site data are:

1. **Current open-water extent** — verify polygons against recent satellite imagery;
   the usable MWp scales with actual water area (rule of thumb ~0.7–1.0 MWp/ha of
   water for FPV, layout-dependent).
2. **Bathymetry** — anchor/mooring design needs depth contours.
3. **Water level fluctuation** — seasonal drawdown range sets mooring load cases and
   dead-shore risk.
4. **Bund/embankment integrity** — especially ex-mining ponds; geotechnical assessment
   of bunds, plus the consequence class if a bund fails.
5. **Ownership/tenure of the water body** — mining lease remnants, state land, or
   private title change the legal path entirely.

If the DEM shows undulating land inside a "floating" site polygon, flag the
contradiction explicitly: either the pond post-dates the DEM epoch or the polygon
includes land. Never average it away.

## Grid interconnection sanity checks

For the route LineString: confirm terrain is benign (no ravine/steep crossing), then
note that the real constraints are usually wayleave/land access (easements under the
National Land Code), road/river/railway crossings, and TNB technical requirements —
none of which the DEM shows. Route length feeds cable-loss and cost estimates.
