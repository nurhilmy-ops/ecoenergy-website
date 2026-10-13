"""Outgoing email: a development outbox (rows in the ``outbox`` table, viewable at
/dev/outbox), SMTP, or the Amazon SES v2 API. Also renders the transactional email templates.

The ``ses`` backend exists because SES offers no SMTP endpoint in Asia Pacific (Malaysia),
ap-southeast-5 — only the HTTPS API — so sending from Malaysia needs the API.

The magic-link and report-ready messages are transactional: they carry no
List-Unsubscribe header but do link to /privacy and /account in the footer.
Newsletter mail (not sent by the MVP) must use ``newsletter_headers``.
"""
from __future__ import annotations

import json
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from functools import lru_cache

import jinja2

from .config import APP_ROOT, Settings
from .db import db, now_iso
from .security import make_unsubscribe_token, unsubscribe_url

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Transport
# ----------------------------------------------------------------------------


def send_mail(settings: Settings, to: str, subject: str, text: str, html: str | None = None,
              headers: dict[str, str] | None = None) -> None:
    """Deliver one message through the configured backend. Raises on SMTP failure."""
    if settings.mail_backend == "outbox":
        with db(settings.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO outbox (to_addr, subject, text_body, html_body, headers_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (to, subject, text, html, json.dumps(headers or {}), now_iso()),
            )
            msg_id = cur.lastrowid
        log.info("[outbox] mail #%s to %s: %r (view at %s/dev/outbox/%s)",
                 msg_id, to, subject, settings.base_url.rstrip("/"), msg_id)
        return
    if settings.mail_backend == "smtp":
        _send_smtp(settings, build_message(settings, to, subject, text, html, headers))
        return
    if settings.mail_backend == "ses":
        _send_ses(settings, build_message(settings, to, subject, text, html, headers))
        return
    raise ValueError(f"Unknown MAIL_BACKEND {settings.mail_backend!r} (expected outbox, smtp or ses)")


def build_message(settings: Settings, to: str, subject: str, text: str, html: str | None = None,
                  headers: dict[str, str] | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to
    msg["Subject"] = subject
    msg["Date"] = formatdate(usegmt=True)
    sender_domain = parseaddr(settings.mail_from)[1].rpartition("@")[2] or None
    msg["Message-ID"] = make_msgid(domain=sender_domain)
    for name, value in (headers or {}).items():
        msg[name] = value
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _send_smtp(settings: Settings, msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    # Port 465 is implicit TLS (SMTPS); anything else is plain SMTP, upgraded with STARTTLS if set.
    if settings.smtp_port == 465:
        smtp_cm = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30, context=context)
    else:
        smtp_cm = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    with smtp_cm as smtp:
        smtp.ehlo()
        if settings.smtp_starttls and settings.smtp_port != 465:
            smtp.starttls(context=context)
            smtp.ehlo()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
    log.info("Sent mail %s via SMTP %s:%s", msg["Message-ID"], settings.smtp_host, settings.smtp_port)


def _send_ses(settings: Settings, msg: EmailMessage) -> None:
    """Send through the SES v2 API as a raw MIME message (keeps our headers intact).
    Credentials come from the standard AWS chain (env vars, profile or instance role)."""
    try:
        import boto3  # optional dependency: pip install boto3
    except ImportError as exc:  # pragma: no cover - exercised only without boto3
        raise RuntimeError("MAIL_BACKEND=ses needs the boto3 package (pip install boto3)") from exc
    client = boto3.client("sesv2", region_name=settings.ses_region)
    resp = client.send_email(
        FromEmailAddress=settings.mail_from,
        Destination={"ToAddresses": [msg["To"]]},
        Content={"Raw": {"Data": msg.as_bytes()}},
    )
    log.info("Sent mail %s via SES %s (MessageId %s)", msg["Message-ID"], settings.ses_region,
             resp.get("MessageId"))


def newsletter_headers(settings: Settings, subscriber_id: int, email: str) -> dict[str, str]:
    """RFC 2369 / RFC 8058 headers every newsletter-type email must carry (``email`` is the
    recipient: unsubscribe values are signed for the id and the address together)."""
    reply = parseaddr(settings.mail_reply_to)[1] or parseaddr(settings.mail_from)[1]
    token = make_unsubscribe_token(settings, subscriber_id, email)
    targets = [f"<{unsubscribe_url(settings, subscriber_id, email)}>"]
    if reply:
        targets.append(f"<mailto:{reply}?subject=unsubscribe%20{token}>")
    return {
        "List-Unsubscribe": ", ".join(targets),
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


# ----------------------------------------------------------------------------
# Templates
# ----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _env() -> jinja2.Environment:
    # .html templates are autoescaped; .txt bodies are plain text and must not be.
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(APP_ROOT / "templates" / "email")),
        autoescape=jinja2.select_autoescape(enabled_extensions=("html",), disabled_extensions=("txt",)),
        trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )


def render_email(settings: Settings, name: str, **context) -> tuple[str, str]:
    """Render templates/email/{name}.txt and .html with the shared footer context."""
    base = settings.base_url.rstrip("/")
    ctx = {
        "base_url": base,
        "privacy_url": f"{base}/privacy",
        "account_url": f"{base}/account",
        "site_url": settings.site_url,
        "ttl_hours": settings.token_ttl_hours,
        "max_uses": settings.token_max_uses,
        "reply_to": settings.mail_reply_to,
        **context,
    }
    env = _env()
    return env.get_template(f"{name}.txt").render(ctx), env.get_template(f"{name}.html").render(ctx)


def send_magic_link_email(settings: Settings, to: str, link: str, newsletter: bool = False) -> None:
    """``newsletter``: the link was requested with the newsletter box ticked and confirms it."""
    text, html = render_email(settings, "magic_link", link=link, newsletter=newsletter)
    send_mail(settings, to, "Your terrain screening link", text, html)


def send_report_ready_email(settings: Settings, to: str, link: str, site_label: str | None) -> None:
    text, html = render_email(settings, "report_ready", link=link, site_label=site_label or "")
    send_mail(settings, to, "Your terrain screening report is ready", text, html)

