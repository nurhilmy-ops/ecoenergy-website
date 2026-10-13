"""Runtime settings, read once from environment variables (and an optional .env file).

Every module receives the same ``Settings`` instance; tests build their own with
``Settings.from_env(overrides)`` so nothing here reads globals at import time
except ``get_settings()``.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent          # terrain-tool/app
PROJECT_ROOT = APP_ROOT.parent                      # terrain-tool/


def _load_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env reader: KEY=VALUE lines, # comments, optional quotes."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def _bool(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- core ---
    app_env: str = "development"                # development | production
    base_url: str = "http://localhost:8000"     # public origin used in emails and Origin checks
    secret_key: str = ""                        # HMAC key for unsubscribe links; generated in dev
    data_dir: Path = PROJECT_ROOT / "data"      # sqlite db + job files live here
    trust_proxy_headers: bool = False           # honour X-Forwarded-For for client IP

    # --- notice / consent ---
    notice_version: str = "2026-10-draft-2"     # bump whenever the privacy notice text changes

    # --- email ---
    mail_backend: str = "outbox"                # outbox (dev: stored in db, shown at /dev/outbox) | smtp | ses
    mail_from: str = "EcoEnergy Consultancy <no-reply@ecoconsultancy.services>"
    mail_reply_to: str = "contact@ecoconsultancy.services"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    ses_region: str = "ap-southeast-5"          # MAIL_BACKEND=ses: SES API region (Malaysia has no SES SMTP endpoint)

    # --- magic links & sessions ---
    token_ttl_hours: int = 72
    token_max_uses: int = 5
    session_ttl_hours: int = 24

    # --- retention (PDPA s.10) ---
    retention_days: int = 30                    # site files, outputs and derived site data
    unverified_purge_days: int = 7              # never-verified email addresses

    # --- abuse controls ---
    rate_link_per_email_hour: int = 3
    rate_link_per_ip_hour: int = 10
    rate_jobs_per_email_day: int = 3
    rate_jobs_per_ip_day: int = 10
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""

    # --- upload limits ---
    max_upload_mb: float = 5.0
    max_kmz_uncompressed_mb: float = 20.0
    max_features: int = 50
    max_extent_km: float = 15.0

    # --- terrain engine ---
    dem_provider: str = "copernicus"            # copernicus | opentopodata | geotiff
    dem_geotiff_path: str = ""                  # used when dem_provider=geotiff (GeoTIFF or VRT, EPSG:4326)
    copernicus_base_url: str = "https://copernicus-dem-30m.s3.amazonaws.com"
    opentopodata_url: str = "https://api.opentopodata.org/v1"
    opentopodata_dataset: str = "srtm30m"
    max_grid_cells: int = 400_000               # cap on DEM cells analysed per job
    contour_min_interval_m: float = 5.0         # never draw contours finer than this

    # --- worker ---
    worker_inline: bool = True                  # run the job worker as a thread inside the web process
    worker_poll_seconds: float = 1.0

    # --- admin ---
    admin_user: str = "admin"                   # HTTP Basic user for /admin
    admin_password: str = ""                    # admin pages disabled (404) while empty

    # --- links ---
    consult_url: str = "https://www.ecoconsultancy.services/consult/"
    site_url: str = "https://www.ecoconsultancy.services/"

    # derived
    extra: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    @property
    def is_dev(self) -> bool:
        return self.app_env != "production"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def max_kmz_uncompressed_bytes(self) -> int:
        return int(self.max_kmz_uncompressed_mb * 1024 * 1024)

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls, overrides: dict | None = None, env_file: Path | None = None) -> "Settings":
        env = _load_dotenv(env_file or (PROJECT_ROOT / ".env"))
        env.update({k: v for k, v in os.environ.items()})
        kwargs: dict = {}
        for f in fields(cls):
            if f.name == "extra":
                continue
            key = f.name.upper()
            if key not in env:
                continue
            raw = env[key]
            default = f.default
            if isinstance(default, bool):
                kwargs[f.name] = _bool(raw)
            elif isinstance(default, int):
                kwargs[f.name] = int(raw)
            elif isinstance(default, float):
                kwargs[f.name] = float(raw)
            elif isinstance(default, Path):
                kwargs[f.name] = Path(raw).expanduser().resolve()
            else:
                kwargs[f.name] = raw
        s = cls(**kwargs)
        if overrides:
            s = replace(s, **overrides)
        s.data_dir.mkdir(parents=True, exist_ok=True)
        s.jobs_dir.mkdir(parents=True, exist_ok=True)
        if not s.secret_key:
            if not s.is_dev:
                raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
            key_file = s.data_dir / ".secret_key"
            if not key_file.exists():
                key_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            s = replace(s, secret_key=key_file.read_text(encoding="utf-8").strip())
        if not s.is_dev and s.mail_backend == "outbox":
            raise RuntimeError("MAIL_BACKEND=outbox is for development only; configure smtp in production")
        return s


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
