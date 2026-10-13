# Sample outputs

Produced on 13 Oct 2026 by the real app (upload over HTTP, Copernicus DEM GLO-30 tiles,
inline worker) from the three test fixtures in `tests/fixtures/`. These are test sites,
not client sites.

| Folder | Fixture | Scheme | Contents |
|---|---|---|---|
| `kedah_flat_paddy/` | `flat_site_kedah.kml`: 42.2 ha paddy with a 2 km cable route | LSS | PDF and Word report, 4 maps, `result.json`, `summary.md` |
| `pahang_bentong_hills/` | `hilly_site_pahang.kml`: 61.9 ha hill lot | LSS | 4 maps, `result.json`, `summary.md` |
| `perak_kinta_fpv_pond/` | `fpv_pond_perak.kml`: 26.7 ha pond | FPV | 4 maps, `result.json`, `summary.md` |

The Perak pond outline was traced from the elevation model, not from imagery or a title
plan, so it may not match a real pond's banks.
