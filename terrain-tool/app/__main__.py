"""``python -m app`` — run the web app (and its inline job worker) with uvicorn.

Listens on 127.0.0.1:$PORT (default 8000). Set HOST=0.0.0.0 only inside a
container or behind a reverse proxy.
"""
from __future__ import annotations

import logging
import os

import uvicorn

from .config import get_settings
from .main import create_app
from .security import redact_query


class RedactTokensFilter(logging.Filter):
    """Keep magic tokens and unsubscribe values out of the uvicorn access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], redact_query(args[2]), *args[3:])
        return True


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    config = uvicorn.Config(
        create_app(settings),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=False,          # client IP handling lives in security.client_ip
        server_header=False,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
    # uvicorn configures its loggers in Config(); attach the filter afterwards.
    logging.getLogger("uvicorn.access").addFilter(RedactTokensFilter())
    logging.getLogger(__name__).info("Terrain screening tool on %s (env=%s, mail=%s, worker_inline=%s)",
                                     settings.base_url, settings.app_env, settings.mail_backend,
                                     settings.worker_inline)
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
