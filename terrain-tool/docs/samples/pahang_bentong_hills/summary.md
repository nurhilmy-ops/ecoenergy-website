# Terrain screening summary

**Site:** Bentong hill lot

- Report: 6HQTpO2DAc32xrmWGCUJBw · generated 2026-10-13T01:36:16+00:00
- Input file: hilly\_site\_pahang.kml (sha256 `a376bb89e6a8980c…`)
- Scheme: lss · stage: land\_secured
- Location: Bentong, Pahang (3.50714°N, 101.90369°E) · EPSG:32647
- DEM: Copernicus DEM GLO-30 — DSM (surface model: includes tree canopy and buildings); epoch 2011–2015 (TanDEM-X acquisitions); vertical datum EGM2008; nominal 30 m, analysed at 30.8 m (1,617 cells, 0.0% without data)

## Totals

- 1 site polygon(s), total 61.86 ha
- 0 route(s), total 0.00 km
- 0 point(s)
- KPKT split (area-weighted): Class I 37.9%, Class II 46.9%, Class III 15.0%, Class IV 0.2%
- Contour interval: 10.0 m

## Sites

| Site | Area (ha) | Elevation min–max (mean) m | Relief m | Slope mean / p90 / max ° | KPKT I / II / III / IV % | Cells |
|---|---:|---|---:|---|---|---:|
| Bentong hill lot | 61.86 | 91.2–193.2 (134.5) | 102.0 | 17.1 / 26.7 / 37.0 | 37.9 / 46.9 / 15.0 / 0.2 | 654 |

Slope bins (% of site area):

| Site | 0-2 | 2-5 | 5-10 | 10-15 | 15-25 | 25-35 | \>35 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Bentong hill lot | 1.2 | 4.4 | 14.8 | 17.4 | 46.9 | 15.0 | 0.2 |

## Flags

- **WARNING — Slopes of 25–35° (KPKT Class III) inside the site.** Share of site area at 25–35° on the DEM — “Bentong hill lot”: 15.0% of its area. Class III ground is restricted under the KPKT hill-land guidelines: development typically needs a geotechnical report and may not be approved. Treat these areas as unusable for layout until a survey and geotechnical assessment say otherwise. *(Source: KPKT hill-land development guidelines (Garis Panduan Perancangan Pembangunan di Kawasan Bukit dan Tanah Tinggi))*
- **CAUTION — Slopes of 15–25° (KPKT Class II) inside the site.** Share of site area at 15–25° on the DEM — “Bentong hill lot”: 46.9% of its area. Under the KPKT hill-land guidelines, Class II ground is generally developable only with engineering controls such as slope protection and erosion and sediment control; expect the local authority to ask for them. *(Source: KPKT hill-land development guidelines (Garis Panduan Perancangan Pembangunan di Kawasan Bukit dan Tanah Tinggi))*
- **CAUTION — More than 10% of site area is steeper than 10°.** Share of site area steeper than 10° — “Bentong hill lot”: 79.5%. Ground this steep typically needs grading or terracing for ground-mounted PV, which adds earthworks cost and erosion-control obligations. Confirm the racking supplier's slope tolerance for the chosen mounting structure before fixing the layout.
- **CAUTION — Elevated terrain — hill or highland guidelines may apply.** Highest DEM elevation — “Bentong hill lot”: up to 193 m (surface model: includes tree canopy). Depending on the state and the local plan, hill or highland development guidelines may apply to land at this elevation. Check with the local planning authority (PBT) before committing to the site.
- **INFO — More than 30 m of elevation change within a site.** Elevation range (highest minus lowest point) — “Bentong hill lot”: 102 m. Plan for an earthworks balance and for stormwater and erosion control designed to MSMA 2nd Edition (DID 2012) at design stage, and allow for them in early cost estimates. *(Source: Urban Stormwater Management Manual for Malaysia (MSMA), 2nd Edition (DID 2012))*
- **INFO — Check EIA requirements for the total area.** Total polygon area is 61.86 ha. Whether an Environmental Impact Assessment is required depends on the activity and area categories in the schedules of the Environmental Quality (Prescribed Activities) (Environmental Impact Assessment) Order 2015, and on factors such as hill land, forest clearing or conversion of agricultural land. Have a qualified EIA consultant check the site against the current schedules. *(Source: Environmental Quality (Prescribed Activities) (Environmental Impact Assessment) Order 2015, under the Environmental Quality Act 1974)*

## Recommended follow-up studies

1. **Licensed topographic survey** — Before layout, earthworks or drainage design, commission a topographic survey by a licensed land surveyor (Licensed Land Surveyors Act 1958), or LiDAR / drone photogrammetry tied to surveyed ground control points.
2. **Geological map review (JMG)** — Review the Jabatan Mineral dan Geosains (JMG) geological map sheet for the site: formation, lithology and any karst or ex-mining ground that affects piling, anchoring or foundations.
3. **Rainfall and climate data (MET Malaysia)** — Obtain climate normals and rainfall records from the nearest MET Malaysia station; rainfall intensity feeds stormwater design to MSMA 2nd Edition.
4. **Surrounding land-use scan (1 / 5 / 10 km)** — Map settlements, schools, rivers and water intakes, forest reserves, industry and mining within 1 km, 5 km and 10 km of the site as context for EIA and SIA scoping.
5. **Land title, zoning and local authority requirements** — Confirm the land title, category of land use and any express conditions, the zoning in the local plan (Rancangan Tempatan), and the requirements of the local authority (PBT) for this type of development.
6. **Geotechnical slope assessment** — Slopes of 25° or more were found inside the site. Commission a geotechnical assessment of slope stability before any layout or earthworks decision.

## Caveats

- Screening grade only: this is a desktop terrain screening from an open global elevation model, not a survey.
- The Copernicus DEM GLO-30 is a surface model: it records the top of tree canopy and buildings, not bare ground. Plantations, forest and built-up areas read higher than the ground beneath them, and slopes at their edges can be exaggerated.
- Elevations show the ground as it was in 2011–2015 (TanDEM-X acquisitions). Ponds, cuttings, platforms and buildings made since then are not represented.
- The nominal 30 m resolution (analysed at about 31 m) smooths out bunds, drains and short steep cuttings, so local slopes are underestimated.
- Site geometry is used exactly as supplied in the uploaded KML/KMZ file; it has not been checked against title plans or survey boundaries.
- Not for authority submissions or design: planning applications, earthworks, drainage and structural design need a licensed survey and qualified engineers.

## Figures

### Site layout

![Site layout](1_site_layout.png)

Site boundaries, routes and points as supplied in the KML, with areas in hectares, on a local UTM grid (EPSG:32647).

### Elevation and contours

![Elevation and contours](2_elevation.png)

Shaded Copernicus DEM GLO-30 surface elevation with contours every 10 m; tree canopy and buildings are included in the surface.

### Slope classes

![Slope classes](3_slope_classes.png)

Slope from the elevation model in seven bands, with the KPKT class boundaries at 15°, 25° and 35°; 37.9% of the site area is KPKT Class I (below 15°).

### Terrain profiles

![Terrain profiles](4_profiles.png)

West–east and south–north sections through “Bentong hill lot”; the vertical scale is exaggerated and not to scale.

---

Copernicus DEM GLO-30 © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018, provided under COPERNICUS by the European Union and ESA; all rights reserved.  
Administrative boundaries: geoBoundaries (gbOpen) — states © OpenStreetMap contributors (ODbL 1.0); districts citypopulation.de (CC BY 3.0).
