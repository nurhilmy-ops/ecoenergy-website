# Sample outputs

Produced on 13 Oct 2026 by the real engine and report renderers (`app.terrain.run_screening`
then `app.reports.build_reports`, Copernicus DEM GLO-30 tiles read over HTTPS) from the three
test fixtures in `tests/fixtures/`. These are test sites, not client sites.

| Folder | Fixture | Scheme | Contents |
|---|---|---|---|
| `kedah_flat_paddy/` | `flat_site_kedah.kml`: 42.2 ha paddy with a 2 km cable route (Kota Setar, Kedah) | LSS | PDF and Word report, 4 maps, `result.json`, `summary.md` |
| `pahang_bentong_hills/` | `hilly_site_pahang.kml`: 61.9 ha hill lot (Bentong, Pahang) | LSS | PDF and Word report, 4 maps, `result.json`, `summary.md` |
| `perak_kinta_fpv_pond/` | `fpv_pond_perak.kml`: 26.7 ha pond (Kinta, Perak) | FPV | 4 maps, `result.json`, `summary.md` |

The Pahang sample shows most of the rule set at work: slope-based KPKT Class II and III
indications, the Tanah Bukit elevation band, the Pahang solar guideline's 10° limit, the
EIA Order 2015 slope item, the Act 133 geotechnical report, ground-mount slope context and
the indicative gross capacity. The Kedah sample is the flat, low-constraint case.

The Perak pond outline was traced from the elevation model, not from imagery or a title
plan, so it may not match a real pond's banks.

Elevation data in these samples: produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014
and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union
and ESA; all rights reserved. The organisations in charge of the Copernicus programme by law
or by delegation do not incur any liability for any use of the Copernicus WorldDEM-30.
State and district boundaries: Department of Statistics Malaysia (DOSM) open data
(github.com/dosm-malaysia/data-open), used under the DOSM Open Data Licence. No endorsement
by DOSM is implied.
