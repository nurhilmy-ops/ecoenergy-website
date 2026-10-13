"""``python -m app`` — run the web app (and its inline job worker) with uvicorn.

Listens on 127.0.0.1:$PORT (default 8000). Set HOST=0.0.0.0 only inside a
container or behind a reverse proxy. HOST, PORT and LOG_LEVEL are read from the
environment or, like every setting, from .env (real environment variables win).
"""
from __future__ import annotations

import logging
import os
from dataclasses import replace
from urllib.parse import urlsplit

import uvicorn

from .config import PROJECT_ROOT, Settings, _load_dotenv, get_settings
from .main import create_app
from .security import redact_query

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_LOG_LEVEL = "INFO"


class RedactTokensFilter(logging.Filter):
    """Keep magic tokens and unsubscribe values out of the uvicorn access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], redact_query(args[2]), *args[3:])
        return True


def process_settings(env_file=None) -> dict:
    """HOST, PORT, LOG_LEVEL (and whether BASE_URL was set) from the environment, then .env."""
    dot = _load_dotenv(env_file or (PROJECT_ROOT / ".env"))

    def get(key: str, default: str) -> str:
        return os.environ.get(key) or dot.get(key) or default

    return {
        "host": get("HOST", DEFAULT_HOST),
        "port": int(get("PORT", str(DEFAULT_PORT))),
        "log_level": get("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
        "base_url_set": bool(os.environ.get("BASE_URL") or dot.get("BASE_URL")),
    }


def align_base_url(settings: Settings, port: int, base_url_set: bool) -> Settings:
    """Email links are built from BASE_URL. Left unset on a non-default PORT, it follows the
    port; set to a localhost URL on another port, it is kept but logged as a likely mistake."""
    if not base_url_set:
        return replace(settings, base_url=f"http://localhost:{port}")
    parts = urlsplit(settings.base_url)
    if parts.hostname in {"localhost", "127.0.0.1", "::1"}:
        url_port = parts.port or (443 if parts.scheme == "https" else 80)
        if url_port != port:
            logging.getLogger(__name__).warning(
                "BASE_URL %s points at port %s but the app listens on port %s: links in emails "
                "will not reach this app. Set BASE_URL=http://localhost:%s (or remove it).",
                settings.base_url, url_port, port, port)
    return settings


def main() -> None:
    proc = process_settings()
    logging.basicConfig(level=proc["log_level"],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = align_base_url(get_settings(), proc["port"], proc["base_url_set"])
    config = uvicorn.Config(
        create_app(settings),
        host=proc["host"],
        port=proc["port"],
        proxy_headers=False,          # client IP handling lives in security.client_ip
        server_header=False,
        log_level=proc["log_level"].lower(),
    )
    # uvicorn configures its loggers in Config(); attach the filter afterwards.
    logging.getLogger("uvicorn.access").addFilter(RedactTokensFilter())
    logging.getLogger(__name__).info("Terrain screening tool on %s (env=%s, mail=%s, worker_inline=%s)",
                                     settings.base_url, settings.app_env, settings.mail_backend,
                                     settings.worker_inline)
    try:
        uvicorn.Server(config).run()
    except KeyboardInterrupt:     # uvicorn re-raises Ctrl+C after a clean shutdown (as uvicorn.run does)
        pass


if __name__ == "__main__":
    main()
