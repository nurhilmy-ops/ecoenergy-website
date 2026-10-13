"""Security helpers: hashing, magic-link tokens, sessions, CSRF, rate limits,
email validation, Turnstile, client IP and the pure-ASGI security middleware.

Rules this module enforces (see docs/ARCHITECTURE.md):
- raw magic tokens and session ids are never stored, only their sha256 hex;
- rate-limit keys are sha256 of the email / IP, never the raw value;
- every response carries the security headers; POSTs with a foreign Origin are refused.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.responses import Response

from .config import Settings
from .db import db, iso, iso_in, now_iso, tx, utcnow

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Hashing
# ----------------------------------------------------------------------------


def sha256_hex(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def email_hash(email: str) -> str:
    """Key used for rate limits and the suppression list (email must be normalised)."""
    return sha256_hex(email.strip().lower())


# ----------------------------------------------------------------------------
# Email validation
# ----------------------------------------------------------------------------

DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "temp-mail.org",
    "yopmail.com", "trashmail.com", "getnada.com", "sharklasers.com",
    "dispostable.com", "maildrop.cc", "tempmail.com", "fakeinbox.com",
})

MAX_EMAIL_LENGTH = 254


class InvalidEmail(ValueError):
    """Raised with a message that is safe to show next to the email field."""


def normalise_email(raw: str) -> str:
    """Validate syntax (no DNS lookups) and return the stored form: ASCII, lower-cased.

    Non-ASCII local parts are refused because plain SMTP relays cannot deliver them;
    internationalised domains are kept in their punycode form.
    """
    from email_validator import EmailNotValidError, validate_email

    candidate = (raw or "").strip()
    if not candidate:
        raise InvalidEmail("Please enter your email address.")
    if len(candidate) > MAX_EMAIL_LENGTH:
        raise InvalidEmail("That email address is too long.")
    try:
        info = validate_email(candidate, check_deliverability=False, allow_smtputf8=False)
    except EmailNotValidError as exc:
        raise InvalidEmail(f"Please check your email address. {exc}") from None
    email = (info.ascii_email or info.normalized).lower()
    if len(email) > MAX_EMAIL_LENGTH:
        raise InvalidEmail("That email address is too long.")
    return email


def is_disposable(email: str) -> bool:
    """True when the domain (or any parent domain) is on the disposable list."""
    domain = email.rsplit("@", 1)[-1].lower().rstrip(".")
    parts = domain.split(".")
    return any(".".join(parts[i:]) in DISPOSABLE_DOMAINS for i in range(len(parts) - 1))


# ----------------------------------------------------------------------------
# Client IP and origins
# ----------------------------------------------------------------------------


def client_ip(request: Request, settings: Settings) -> str:
    """Peer address, or the first X-Forwarded-For hop when we sit behind a trusted proxy."""
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for", "")
        first = fwd.split(",")[0].strip()
        if first:
            return first[:64]
    return request.client.host if request.client else "unknown"


def origin_of(url: str) -> str:
    """scheme://host[:port], lower-cased, default ports dropped. '' when not an http(s) URL."""
    try:
        parts = urlsplit((url or "").strip())
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return ""
    if scheme not in {"http", "https"} or not host:
        return ""
    if ":" in host:                      # IPv6 literal
        host = f"[{host}]"
    if port is None or (scheme, port) in {("http", 80), ("https", 443)}:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


_SAFE_NEXT = re.compile(r"^/reports/[A-Za-z0-9_\-]{1,64}/?$")


def safe_next_path(path: str | None) -> str | None:
    """Only same-site report paths are allowed as post-login redirects (no open redirect)."""
    if not path or not isinstance(path, str):
        return None
    if _SAFE_NEXT.match(path) and "//" not in path and "\\" not in path:
        return path
    return None


# ----------------------------------------------------------------------------
# Rate limiting (events table)
# ----------------------------------------------------------------------------


def _window_start(window_seconds: int) -> str:
    return iso(utcnow() - timedelta(seconds=window_seconds))


def rate_limit(settings: Settings, kind: str, raw_key: str, limit: int, window_seconds: int) -> bool:
    """Return True and record an event if fewer than ``limit`` events of ``kind`` exist for
    ``raw_key`` within the window; otherwise return False and record nothing."""
    return rate_limit_all(settings, [(kind, raw_key, limit, window_seconds)])


def rate_limit_all(settings: Settings, checks: list[tuple[str, str, int, int]]) -> bool:
    """All-or-nothing version of ``rate_limit``: records an event for every
    (kind, raw_key, limit, window_seconds) only if none of them is exhausted, so a
    refusal on one key never burns quota on another."""
    with tx(settings.db_path) as conn:
        for kind, raw_key, limit, window_seconds in checks:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM events WHERE kind = ? AND key = ? AND created_at > ?",
                (kind, sha256_hex(raw_key), _window_start(window_seconds)),
            ).fetchone()
            if count >= limit:
                return False
        now = now_iso()
        conn.executemany("INSERT INTO events (kind, key, created_at) VALUES (?, ?, ?)",
                         [(kind, sha256_hex(raw_key), now) for kind, raw_key, _, _ in checks])
        return True


def record_event(settings: Settings, kind: str, raw_key: str) -> None:
    """Record an event unconditionally (e.g. a failed admin login)."""
    with db(settings.db_path) as conn:
        conn.execute("INSERT INTO events (kind, key, created_at) VALUES (?, ?, ?)",
                     (kind, sha256_hex(raw_key), now_iso()))


def rate_remaining(settings: Settings, kind: str, raw_key: str, limit: int, window_seconds: int) -> int:
    """How many more events the key may record in the current window (read-only)."""
    with db(settings.db_path) as conn:
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM events WHERE kind = ? AND key = ? AND created_at > ?",
            (kind, sha256_hex(raw_key), _window_start(window_seconds)),
        ).fetchone()
    return max(0, limit - count)


# ----------------------------------------------------------------------------
# Magic-link tokens
# ----------------------------------------------------------------------------


def create_magic_token(settings: Settings, subscriber_id: int, next_path: str | None = None,
                       conn: sqlite3.Connection | None = None) -> str:
    """Insert a token row (hash only) and return the raw token for the email link."""
    raw = secrets.token_urlsafe(32)
    row = (subscriber_id, sha256_hex(raw), safe_next_path(next_path), now_iso(),
           iso_in(hours=settings.token_ttl_hours), settings.token_max_uses)
    sql = ("INSERT INTO tokens (subscriber_id, token_hash, next_path, created_at, expires_at, uses_left) "
           "VALUES (?, ?, ?, ?, ?, ?)")
    if conn is not None:
        conn.execute(sql, row)
    else:
        with db(settings.db_path) as c:
            c.execute(sql, row)
    return raw


def magic_link(settings: Settings, raw_token: str) -> str:
    return f"{settings.base_url.rstrip('/')}/start?t={raw_token}"


def _plausible_token(raw: str | None) -> bool:
    return bool(raw) and len(raw) <= 128 and re.fullmatch(r"[A-Za-z0-9_\-]+", raw) is not None


def peek_token(settings: Settings, raw: str | None) -> sqlite3.Row | None:
    """Return the token row if it is currently usable. Never consumes a use."""
    if not _plausible_token(raw):
        return None
    with db(settings.db_path) as conn:
        return conn.execute(
            "SELECT * FROM tokens WHERE token_hash = ? AND uses_left > 0 AND expires_at > ?",
            (sha256_hex(raw), now_iso()),
        ).fetchone()


def consume_token(settings: Settings, raw: str | None, conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Atomically validate and spend one use. Must run inside the caller's transaction."""
    if not _plausible_token(raw):
        return None
    token_hash = sha256_hex(raw)
    cur = conn.execute(
        "UPDATE tokens SET uses_left = uses_left - 1 "
        "WHERE token_hash = ? AND uses_left > 0 AND expires_at > ?",
        (token_hash, now_iso()),
    )
    if cur.rowcount != 1:
        return None
    return conn.execute("SELECT * FROM tokens WHERE token_hash = ?", (token_hash,)).fetchone()


# ----------------------------------------------------------------------------
# Sessions and CSRF
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Session:
    id_hash: str
    subscriber_id: int
    email: str
    csrf: str
    expires_at: str


def session_cookie_name(settings: Settings) -> str:
    # The __Host- prefix pins the cookie to this exact origin (needs Secure, Path=/, no Domain).
    return "__Host-tt_session" if settings.secure_cookies else "tt_session"


def preauth_cookie_name(settings: Settings) -> str:
    return "__Host-tt_pre" if settings.secure_cookies else "tt_pre"


def create_session(settings: Settings, subscriber_id: int, conn: sqlite3.Connection | None = None) -> str:
    """Create a server-side session and return the raw cookie value."""
    raw = secrets.token_urlsafe(32)
    row = (sha256_hex(raw), subscriber_id, secrets.token_urlsafe(32), now_iso(),
           iso_in(hours=settings.session_ttl_hours))
    sql = "INSERT INTO sessions (id, subscriber_id, csrf, created_at, expires_at) VALUES (?, ?, ?, ?, ?)"
    if conn is not None:
        conn.execute(sql, row)
    else:
        with db(settings.db_path) as c:
            c.execute(sql, row)
    return raw


def load_session(settings: Settings, request: Request) -> Session | None:
    raw = request.cookies.get(session_cookie_name(settings))
    if not raw or len(raw) > 128:
        return None
    with db(settings.db_path) as conn:
        row = conn.execute(
            "SELECT s.id, s.subscriber_id, s.csrf, s.expires_at, sub.email "
            "FROM sessions s JOIN subscribers sub ON sub.id = s.subscriber_id "
            "WHERE s.id = ? AND s.expires_at > ?",
            (sha256_hex(raw), now_iso()),
        ).fetchone()
    if row is None:
        return None
    return Session(row["id"], row["subscriber_id"], row["email"], row["csrf"], row["expires_at"])


def destroy_session(settings: Settings, request: Request) -> None:
    raw = request.cookies.get(session_cookie_name(settings))
    if raw:
        with db(settings.db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (sha256_hex(raw),))


def set_session_cookie(response: Response, settings: Settings, raw: str) -> None:
    response.set_cookie(
        session_cookie_name(settings), raw,
        max_age=settings.session_ttl_hours * 3600, path="/",
        httponly=True, samesite="lax", secure=settings.secure_cookies,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(session_cookie_name(settings), path="/", httponly=True,
                           samesite="lax", secure=settings.secure_cookies)


def set_preauth_cookie(response: Response, settings: Settings, value: str) -> None:
    # Double-submit value for POST /start (login-CSRF guard). Strict: never sent cross-site.
    response.set_cookie(preauth_cookie_name(settings), value, max_age=3600, path="/",
                        httponly=True, samesite="strict", secure=settings.secure_cookies)


def verify_csrf(session: Session | None, submitted: Any) -> bool:
    if session is None or not isinstance(submitted, str) or not submitted:
        return False
    return hmac.compare_digest(session.csrf.encode(), submitted.encode())


def tokens_equal(a: Any, b: Any) -> bool:
    if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
        return False
    return hmac.compare_digest(a.encode(), b.encode())


# ----------------------------------------------------------------------------
# Signed unsubscribe values
# ----------------------------------------------------------------------------


def _unsubscribe_sig(settings: Settings, subscriber_id: int) -> str:
    mac = hmac.new(settings.secret_key.encode(), f"unsubscribe:{subscriber_id}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


def make_unsubscribe_token(settings: Settings, subscriber_id: int) -> str:
    return f"{subscriber_id}.{_unsubscribe_sig(settings, subscriber_id)}"


def verify_unsubscribe_token(settings: Settings, value: str | None) -> int | None:
    """Return the subscriber id if the signature is valid, else None."""
    if not value or len(value) > 128 or "." not in value:
        return None
    sid, sig = value.split(".", 1)
    if not sid.isdigit():
        return None
    if not hmac.compare_digest(_unsubscribe_sig(settings, int(sid)).encode(), sig.encode()):
        return None
    return int(sid)


def unsubscribe_url(settings: Settings, subscriber_id: int) -> str:
    return f"{settings.base_url.rstrip('/')}/unsubscribe?u={make_unsubscribe_token(settings, subscriber_id)}"


# ----------------------------------------------------------------------------
# Cloudflare Turnstile
# ----------------------------------------------------------------------------

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_enabled(settings: Settings) -> bool:
    return bool(settings.turnstile_site_key)


def verify_turnstile(settings: Settings, response_token: str | None, ip: str | None) -> bool:
    """Server-side Turnstile check. Always True when Turnstile is not configured."""
    if not turnstile_enabled(settings):
        return True
    if not settings.turnstile_secret_key:
        log.error("TURNSTILE_SITE_KEY is set but TURNSTILE_SECRET_KEY is empty; refusing sign-ups")
        return False
    if not response_token or len(response_token) > 4096:
        return False
    import requests

    data = {"secret": settings.turnstile_secret_key, "response": response_token}
    if ip and ip != "unknown":
        data["remoteip"] = ip
    try:
        resp = requests.post(TURNSTILE_VERIFY_URL, data=data, timeout=10)
        return bool(resp.json().get("success"))
    except Exception:  # network error, bad JSON: fail closed but keep the page working
        log.warning("Turnstile verification request failed", exc_info=True)
        return False


# ----------------------------------------------------------------------------
# ASGI middleware: security headers, Origin check, request body cap
# ----------------------------------------------------------------------------

CSP = ("default-src 'self'; img-src 'self' data:; "
       "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
       "font-src https://fonts.gstatic.com; "
       "script-src 'self' https://challenges.cloudflare.com; "
       "frame-src https://challenges.cloudflare.com; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")

SECURITY_HEADERS = {
    "content-security-policy": CSP,
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "cross-origin-opener-policy": "same-origin",
}

UPLOAD_PATH = "/upload"
UNSUBSCRIBE_PATH = "/unsubscribe"
SMALL_BODY_LIMIT = 64 * 1024            # every POST except the upload form
UPLOAD_FORM_OVERHEAD = 64 * 1024        # multipart framing + the small text fields


class BodyTooLarge(Exception):
    """Raised from the wrapped ``receive`` when a request body exceeds its cap."""


class SecurityMiddleware:
    """Pure ASGI (no BaseHTTPMiddleware) so request streaming stays intact."""

    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings
        self.allowed_origin = origin_of(settings.base_url)

    def body_limit(self, path: str) -> int:
        if path == UPLOAD_PATH:
            return self.settings.max_upload_bytes + UPLOAD_FORM_OVERHEAD
        return SMALL_BODY_LIMIT

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")
        settings = self.settings

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for k, v in SECURITY_HEADERS.items():
                    headers[k] = v
                if settings.secure_cookies:
                    headers["strict-transport-security"] = "max-age=31536000"
                if "cache-control" not in headers:
                    # Pages can carry tokens or personal data; only static assets are cacheable.
                    headers["cache-control"] = ("public, max-age=3600" if path.startswith("/static/")
                                                else "no-store")
            await send(message)

        if method not in {"GET", "HEAD", "OPTIONS"}:
            req_headers = Headers(scope=scope)
            origin = req_headers.get("origin")
            # Browsers send "Origin: null" for our own form posts because every page is served
            # with Referrer-Policy: no-referrer (Fetch spec); it carries no information, so it is
            # treated like an absent header and the CSRF / pre-auth tokens do the protecting.
            if (origin is not None and origin.strip().lower() != "null"
                    and origin_of(origin) != self.allowed_origin and path != UNSUBSCRIBE_PATH):
                log.warning("Rejected cross-origin %s %s from Origin %s", method, path, origin[:100])
                await _plain_response(send_with_headers, 403,
                                      "Cross-origin form submission refused. "
                                      f"Please open the tool at {settings.base_url} and try again.")
                return

            limit = self.body_limit(path)
            declared = req_headers.get("content-length", "")
            declared_too_large = declared.isdigit() and int(declared) > limit
            if declared_too_large and path != UPLOAD_PATH:
                await _plain_response(send_with_headers, 413, "Request too large.")
                return
            received = 0

            async def limited_receive():
                # The upload route catches BodyTooLarge to re-render its form with a friendly
                # message; a declared oversize upload fails on the first read, before buffering.
                nonlocal received
                if declared_too_large:
                    raise BodyTooLarge()
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > limit:
                        raise BodyTooLarge()
                return message

            await self.app(scope, limited_receive, send_with_headers)
            return

        await self.app(scope, receive, send_with_headers)


async def _plain_response(send, status: int, text: str) -> None:
    body = text.encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def redact_query(path_with_query: str) -> str:
    """Hide magic tokens / unsubscribe values in anything that gets logged."""
    if "?" not in path_with_query:
        return path_with_query
    path, query = path_with_query.split("?", 1)
    params = parse_qs(query, keep_blank_values=True)
    if not ({"t", "u"} & params.keys()):
        return path_with_query
    return path + "?" + "&".join(f"{k}=[redacted]" if k in {"t", "u"} else f"{k}=…" for k in params)
