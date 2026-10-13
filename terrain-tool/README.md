# EcoEnergy terrain screening tool (local model)

A lead-magnet web tool: a visitor confirms their email through a magic link, uploads a
KML/KMZ of their site and gets a desktop terrain screening on screen, as a PDF and as a
Word file. It covers area, elevation, KPKT slope classes, profiles, rule-based flags and
recommended follow-up studies. Elevations come from the Copernicus DEM GLO-30, read over
HTTPS, so the machine running the tool needs internet access.

- Sample outputs, no setup needed: [`docs/samples/`](docs/samples/)
- Screenshots of every page: [`docs/screenshots/`](docs/screenshots/)
- Module contract, `result.json` schema and security rules: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Run it locally

Needs Python 3.11 or newer.

```bash
./run_local.sh            # macOS / Linux
.\run_local.ps1           # Windows PowerShell
```

The script creates `.venv`, installs `requirements.txt`, copies `.env.example` to `.env`
on first run, and starts the app on http://localhost:8000.

1. Open http://localhost:8000 and enter any email address.
2. In development, emails are not sent: open http://localhost:8000/dev/outbox and click
   the link in "Your terrain screening link".
3. Press **Continue**, upload a KML/KMZ, for example `tests/fixtures/flat_site_kedah.kml`,
   and wait a few seconds for the report.

To see the admin pages (leads, subscribers, CSV exports), set `ADMIN_PASSWORD` in `.env`
and open http://localhost:8000/admin.

With Docker, `docker compose up --build` starts the app together with Mailpit, a local
mail catcher. Magic-link emails then arrive at http://localhost:8025.

## Configuration

Settings come from environment variables or `.env`; see `.env.example` and
`app/config.py`. Production needs `APP_ENV=production`, a `SECRET_KEY`, SMTP settings
(`MAIL_BACKEND=smtp`) and an `https://` `BASE_URL`.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The suite runs offline. To also run the real Copernicus download:
`RUN_NETWORK_TESTS=1 python -m pytest -q -m network`.
