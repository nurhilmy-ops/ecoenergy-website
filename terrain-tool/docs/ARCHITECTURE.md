# Terrain Screening Tool — architecture and module contract

First local model of the EcoEnergy lead-magnet tool: a visitor gives an email address,
confirms it through a magic link, uploads a KML/KMZ, and gets a desktop terrain
screening on the page plus PDF and Word downloads.

This document is the contract every module is written against. If code and this
document disagree, fix one of them in the same change.

## Request flow

```
LinkedIn / Threads / newsletter post ──(utm-tagged link)──▶  GET /            email + optional newsletter tick (unticked)
                                                              POST /request-link
                                                                │  rate limits, disposable-domain block, Turnstile (if configured)
                                                                │  upsert subscriber, ledger: service granted (+ newsletter granted
                                                                │  only if ticked), token (sha256 stored)
                                                                ▼
                                                              mail: "Your terrain screening link"  (outbox in dev / SMTP)
                                                                ▼
                                                              GET  /start?t=…   page with a Continue button (does NOT consume the token,
                                                                                so Microsoft Safe Links / scanners can prefetch safely)
                                                              POST /start       consumes one use, verifies email, confirms pending consents,
                                                                                creates session cookie → /upload (or validated next path)
                                                              GET  /upload      KML/KMZ + optional scheme / stage / site label / notes
                                                                                + separate, unticked "staff may email me about this site" box
                                                              POST /upload      validate (size, XML safety, geometry, Malaysia, extent) →
                                                                                job row (+ site_followup granted with job_id, if ticked) → /reports/{id}
                                                                ▼
                                    worker thread  ──▶  app.terrain.run_screening(...)  → PNGs + result.json + summary.md
                                                   ──▶  app.reports.build_reports(...)   → report.pdf + report.docx
                                                   ──▶  mail: "Your report is ready" (fresh magic link with next=/reports/{id})
                                                                ▼
                                                              GET /reports/{id}  status page → result page (maps, tables, flags, downloads,
                                                                                 CTA to /consult/, follow-up choice with a one-click
                                                                                 change, data notices, delete-now button)
                                                              POST /reports/{id}/followup   grant | withdraw (CSRF) → ledger row
                                                              GET  /account      what we hold, follow-up per report, consent history,
                                                                                 JSON export, delete everything
```

## Directory layout

```
terrain-tool/
  app/
    __init__.py
    __main__.py          python -m app  → runs uvicorn with settings
    config.py            Settings (env / .env)                         [shared, do not fork]
    db.py                schema + connection helpers                   [shared, do not fork]
    main.py              FastAPI app factory create_app(settings) and all routes
    security.py          tokens, sessions, CSRF, rate limits, email validation, Turnstile, client IP
    mailer.py            send_mail(settings, to, subject, text, html, headers) → outbox | smtp
    jobs.py              enqueue/claim/process + worker thread + retention sweeps
    admin.py             admin router (HTTP Basic), CSV exports
    terrain/             screening engine (ported from the kml-terrain-screening skill)
      __init__.py        public API: ScreeningError, SiteInput, validate_upload, run_screening
      kml.py             safe KML/KMZ parsing (defusedxml, zip limits, 2.2/2.1/no namespace)
      dem.py             DEM providers: copernicus (COG over HTTPS), opentopodata, geotiff
      analysis.py        grid, slope, polygon masks, KPKT split, stats, profiles
      figures.py         four PNG figures (matplotlib OO API, no pyplot — thread safe)
      flags.py           rule-based flags, follow-ups and caveats (all report wording lives here)
      boundaries.py      state/district lookup from the bundled DOSM district boundaries
    reports/
      __init__.py        public API: build_reports
      content.py         turns result.json into an ordered list of blocks shared by PDF + DOCX
      pdf.py             ReportLab renderer
      docx.py            python-docx renderer
    templates/           Jinja2 pages + email templates (_followup_form.html: the per-report follow-up button)
    static/              css, logo, small JS (status polling)
    data/boundaries/     dosm_administrative_2_district.geojson: DOSM's 160 districts with their state
                         (github.com/dosm-malaysia/data-open, DOSM Open Data Licence)
  tests/
  docs/ARCHITECTURE.md
  requirements.txt  Dockerfile  docker-compose.yml  .env.example  run_local.sh  run_local.ps1  README.md
```

## Public Python interfaces

### `app.terrain`

```python
class ScreeningError(Exception):
    """Message is safe to show to the visitor. `code` is a short machine key."""
    def __init__(self, message: str, code: str = "screening_error"): ...
    message: str                  # same text as str(exc)
    code: str

@dataclass
class Feature:
    name: str
    kind: str                     # "polygon" | "line" | "point"
    coords: list[tuple[float, float]]          # (lon, lat); polygon = exterior ring, stored open
    holes: list[list[tuple[float, float]]] = []  # polygon interior rings, stored open (default empty)

@dataclass
class SiteInput:
    features: list[Feature]
    bbox: tuple[float, float, float, float]    # (min_lon, min_lat, max_lon, max_lat) of all features
    extent_km: float                           # max of bbox width/height in km
    source_filename: str
    repaired: list[str] = []                   # names of self-intersecting polygons fixed with
                                               # make_valid (largest part kept); reported as caveats

def validate_upload(path: Path, settings: Settings, original_filename: str) -> SiteInput:
    """Parse and validate an uploaded .kml/.kmz. Raises ScreeningError for: unsupported type,
    file too large, unsafe XML (entities/DTD), KMZ without a .kml or exceeding the uncompressed cap,
    no usable geometry, more than settings.max_features features, any coordinate outside the
    Malaysia envelope (lon 99.0–120.0, lat 0.5–8.0), or extent > settings.max_extent_km."""

def run_screening(path: Path, out_dir: Path, settings: Settings, meta: dict, *,
                  dem_fetcher: Callable[[Bbox, Settings], DemGrid] | None = None) -> dict:
    """Validate + analyse + draw. Writes into out_dir:
         1_site_layout.png, 2_elevation.png, 3_slope_classes.png, 4_profiles.png,
         result.json, summary.md
       Returns the result dict (same content as result.json). `meta` keys:
         report_id, generated_at (ISO UTC), site_label, scheme, stage, input_filename.
       Raises ScreeningError on user-fixable problems and on DEM unavailability
       (message must say the DEM service could not be reached, never fabricate elevations).
       dem_fetcher (tests only) replaces the provider chosen by settings.dem_provider."""
```

`ScreeningError.code` values: `unsupported_type`, `file_too_large`, `unsafe_xml`,
`invalid_kml`, `invalid_kmz`, `kmz_no_kml`, `kmz_too_large`, `unreadable_file`,
`invalid_coordinates`, `invalid_polygon`, `invalid_line`, `too_complex` (> 250,000 vertices),
`no_geometry`, `too_many_features`, `outside_malaysia`, `extent_too_large`,
`dem_unavailable`, `no_dem_coverage`; `jobs.py` adds `input_missing`. Codes are for logs
only; the visitor sees the message.

### `app.reports`

```python
def build_reports(result: dict, out_dir: Path, settings: Settings) -> dict[str, Path]:
    """Render report.pdf and report.docx into out_dir from result (+ the PNGs it references,
    which live in out_dir). Returns {"pdf": Path, "docx": Path}."""
```

### `app.mailer`

```python
def send_mail(settings, to: str, subject: str, text: str, html: str | None = None,
              headers: dict[str, str] | None = None) -> None
```

## `result.json` (schema_version 1)

All numbers are plain floats (rounded sensibly), never NaN — use `null` when unknown.
`dem.disclaimer`, `dem.sends_coordinates_to_third_party` and `sites[].steeper_than_grade_pct`
were added after schema_version 1 first shipped, without a version bump: readers must use
`.get()` for them so result.json files written before the change still render (the result
page does; `tests/test_flow.py` checks an old-format file). The `//` comments below are
documentation only.

```json
{
  "schema_version": 1,
  "meta": {
    "report_id": "str", "generated_at": "2026-10-13T08:00:00+00:00",
    "site_label": "str|null", "scheme": "lss|cress|fpv|rooftop|other|null",
    "stage": "exploring|land_secured|bidding|other|null",
    "input_filename": "str", "input_sha256": "hex"
  },
  "dem": {
    "provider": "copernicus|opentopodata|geotiff",
    "name": "Copernicus DEM GLO-30",
    "model_type": "DSM (surface model: includes tree canopy and buildings)",
    "epoch": "December 2010 – January 2015 (TanDEM-X acquisitions)",
    "vertical_datum": "EGM2008",
    "nominal_resolution_m": 30,
    "grid_spacing_m": 30.7,
    "cells_analysed": 123456,
    "nodata_pct": 0.0,
    "attribution": "str",
    "disclaimer": "str|null",                    // licence notice that must travel with the data
                                                 // (Copernicus: the liability sentence); null if none
    "sends_coordinates_to_third_party": false    // true when exact site coordinates went to an outside
                                                 // service (opentopodata); copernicus requests 1° tile
                                                 // names only, geotiff reads a local file
  },
  "location": {
    "centroid_lon": 101.7, "centroid_lat": 3.1,
    "state": "Selangor|null", "district": "Petaling|null",
    "utm_epsg": "EPSG:32647",
    "boundary_attribution": "str"               // DOSM open data credit + no-endorsement sentence
  },
  "totals": {
    "polygon_count": 1, "line_count": 0, "point_count": 0,
    "total_area_ha": 42.3, "total_line_km": 0.0
  },
  "sites": [{
    "name": "str", "area_ha": 42.3, "perimeter_m": 2900.0, "centroid": [101.7, 3.1],
    "elev_min_m": 20.0, "elev_max_m": 48.0, "elev_mean_m": 31.2, "relief_m": 28.0,
    "slope_mean_deg": 3.1, "slope_p90_deg": 7.4, "slope_max_deg": 16.0,
    "kpkt_pct":   {"I": 98.0, "II": 2.0, "III": 0.0, "IV": 0.0},
    "slope_bins_pct": {"0-2": 40.0, "2-5": 35.0, "5-10": 15.0, "10-15": 8.0,
                        "15-25": 2.0, "25-35": 0.0, ">35": 0.0},
    "steeper_than_grade_pct": {"10": 12.0, "15": 4.0},   // % of site area steeper than a 10% / 15% grade
    "cells": 450
  }],
  "kpkt_overall_pct": {"I": 98.0, "II": 2.0, "III": 0.0, "IV": 0.0},
  "routes": [{"name": "str", "length_km": 3.2, "elev_min_m": 10.0, "elev_max_m": 40.0,
               "total_ascent_m": 55.0, "max_grade_pct": 12.0}],
  "points": [{"name": "str", "lon": 101.7, "lat": 3.1, "elev_m": 22.0}],
  "contour_interval_m": 5.0,
  "flags": [{"level": "info|caution|warning", "code": "str", "title": "str", "detail": "str",
             "source": "str|null"}],
  "followups": [{"title": "str", "detail": "str"}],
  "caveats": ["str"],
  "figures": [{"file": "1_site_layout.png", "title": "str", "caption": "str"}]
}
```

KPKT classes are computed per site **inside the polygon** (cell centres within the
exterior ring and outside holes), area-weighted for `kpkt_overall_pct`. Class
boundaries: I < 15°, II 15–25°, III 25–35°, IV ≥ 35°.

Flags, follow-ups and caveats are produced by `app/terrain/flags.py` from `result` alone
(all report wording lives there, each flag naming the instrument it relies on in `source`).
The state from the DOSM lookup selects state-specific rules (for example `pahang_solar_10deg`,
`penang_hill`); slope rules include the KPKT classes (`kpkt_class_ii` … `kpkt_class_iv`) and
the EIA Order slope item (`eia_slope_item13`). With `scheme = "fpv"` the ground-mount flags
(`steep_for_ground_pv`, `all_class_i`) are not raised; the FPV flags (`fpv_dem_epoch`,
`fpv_land_inside`) and FPV follow-ups are.

`location.state` / `location.district` come from DOSM's district layer, which carries both
names (DOSM spelling). A point outside every polygon (offshore, or in a simplification gap)
falls back to the nearest district within 5 km, otherwise both are `null`.

## Consent model (PDPA)

Each purpose has its own control and its own rows in the append-only `consents` ledger
(PDP Regulations 2013 reg 3(1) record-keeping; reg 3(2): a consent request must be
distinguishable in appearance from other matters; the General Code of Practice para 4.2:
the notice is not the place for blanket consent). Every row stores the exact wording shown
(`consent_wording(key)`: English + Bahasa Malaysia), `notice_version`, IP, user agent and time.

| Purpose | Where it is asked | Scope | Ledger actions | State column |
|---|---|---|---|---|
| `service` | landing notice (required to use the tool) | account (`job_id` NULL) | granted → confirmed on `POST /start` | — |
| `newsletter` | separate unticked box on the landing form, or the account page | account | granted → confirmed (double opt-in); withdrawn on unsubscribe | `subscribers.newsletter_status` |
| `site_followup` | separate unticked box on the upload page, per report | one job (`consents.job_id`) | granted at upload if ticked; granted / withdrawn by `POST /reports/{id}/followup` from the result page or `/account` | `jobs.followup_consent` (0/1) |

- `/request-link` records only `service` (and `newsletter` if ticked). It never grants
  follow-up. `confirm_subscriber` confirms account-level purposes only; per-report
  consents are given by a signed-in, verified visitor and need no confirmation.
- `POST /reports/{id}/followup` (session + CSRF, owner only, not for deleted reports)
  appends a row only when the choice changes, so repeated clicks add nothing. Withdrawal
  (PDPA s.38) takes effect at once: the job drops out of the leads CSV.
- Deleting a report, by the visitor or by retention, sets `followup_consent = 0` with the
  site fields; the ledger keeps the history (reg 3(5): the burden of proving consent is on
  the data user). Erasing the account deletes the ledger with the subscriber (cascade) and
  leaves sha256(email) in `suppression`. How long consent records should outlive an erased
  account is an open legal-review item.
- Admin: `/admin/leads` lists one row per live screening with Follow-up yes/no and a
  "Do not contact" badge; `/admin/export/leads.csv` contains ONLY screenings whose
  follow-up consent is currently granted; `/admin/export/newsletter.csv` only
  `newsletter_status = 'subscribed'`.
- Before the unbundling, `/request-link` granted `site_followup` at account level. Those
  rows (`job_id` NULL) stay as history but are not treated as consent: migrated jobs start
  at `followup_consent = 0`.

## Database and migrations

SQLite in `DATA_DIR/app.db` (WAL), one short-lived connection per call site; the schema
(`app/db.py`) avoids SQLite-only types so it can move to Postgres. `init_db` runs on every
start: `CREATE TABLE IF NOT EXISTS`, then `migrate()`, which adds any column listed in
`COLUMN_MIGRATIONS` that an existing database lacks (`PRAGMA table_info` check inside one
`BEGIN IMMEDIATE` transaction, so it is idempotent and safe if two processes start at once),
then creates indexes on migrated columns. Add a new column to both `SCHEMA` and
`COLUMN_MIGRATIONS`.

## Security and privacy rules (apply everywhere)

- Raw magic tokens and session ids are never stored — only sha256 hashes.
- `GET /start` never consumes a token. Only `POST /start` does.
- `Referrer-Policy: no-referrer` on every response (token URLs must not leak to font CDNs).
- Every state-changing POST that has a session also carries the session CSRF token;
  all POSTs reject a mismatched `Origin` header. `Origin: null` is treated as absent:
  browsers send it on the site's own form posts because of `Referrer-Policy: no-referrer`.
  `POST /unsubscribe` (RFC 8058 one-click) is exempt from the Origin check.
- `POST /start` has no session yet, so it uses a pre-auth double-submit token instead:
  `GET /start` sets an HttpOnly, SameSite=Strict cookie (`tt_pre`, `__Host-tt_pre` on
  https) and the same value in a hidden `pre` field; a mismatch re-shows the Continue
  page without consuming the magic link (login-CSRF protection).
- A job counts against the daily job limits only after `validate_upload` accepts the
  file; upload attempts are capped separately per IP.
- The newsletter tick box is unticked by default and separate from tool access;
  newsletter becomes `subscribed` only after the email is verified (double opt-in).
- Staff follow-up is a separate, unticked box per report on the upload page, changeable
  per report afterwards; the landing notice only says that it is a choice made there
  (see "Consent model").
- The same response is returned whether or not an email already exists (no enumeration).
- Job ids are unguessable and job pages additionally require the owning session.
- Site files, outputs and derived site fields are deleted after `retention_days`
  or immediately on "Delete now" (follow-up for that site ends with them); erasing an
  account adds sha256(email) to `suppression`.
- The elevation provider decides what leaves the server: `copernicus` requests 1° tile
  names only, `opentopodata` sends the site's sample coordinates (shown on the result page
  via `dem.sends_coordinates_to_third_party`, and in the privacy notice when configured),
  `geotiff` sends nothing.
- Uploaded XML is parsed with defusedxml; KMZ members are size-capped before reading.
- No KML text (names, descriptions) is ever passed to an LLM; all wording is rule-based.

## Tests

- `tests/test_kml.py`, `tests/test_analysis.py`: engine with synthetic DEMs; one opt-in
  network test (`RUN_NETWORK_TESTS=1`, marker `network`) runs real Copernicus tiles.
- `tests/test_reports.py`: PDF/DOCX renderers from `tests/fixtures/sample_result.json`.
- `tests/test_flow.py`, `tests/test_security.py`, `tests/test_jobs.py`: web app with fake
  `app.terrain` / `app.reports` modules (`fake_engine` fixture in `conftest.py`): consent
  unbundling and per-report follow-up, admin exports, privacy notice content, old-format
  result.json, the in-place migration of a pre-unbundling database, and a check that
  `.env.example` and the README list every `Settings` field with its default.
- `tests/test_integration.py`: the real app, engine and renderers together over HTTP,
  with a synthetic GeoTIFF through the `geotiff` DEM provider (offline). It also checks
  `result.json` against the key sets above.
