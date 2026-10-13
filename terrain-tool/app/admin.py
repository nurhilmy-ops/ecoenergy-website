"""Admin pages (HTTP Basic) and CSV exports, mounted at /admin.

Disabled (404) while ADMIN_PASSWORD is empty. Failed logins are rate-limited per IP.
"""
from __future__ import annotations

import base64
import csv
import io
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from .config import Settings
from .db import db, now_iso
from .security import client_ip, rate_remaining, record_event, unsubscribe_url

log = logging.getLogger(__name__)

MAX_FAILED_LOGINS_PER_HOUR = 20
REALM_HEADER = {"WWW-Authenticate": 'Basic realm="EcoEnergy terrain admin", charset="UTF-8"'}


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _basic_credentials(request: Request) -> tuple[str, str] | None:
    """Parse an Authorization: Basic header; None when absent or malformed."""
    scheme, _, param = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic" or not param:
        return None
    try:
        decoded = base64.b64decode(param.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    user, sep, password = decoded.partition(":")
    return (user, password) if sep else None


def require_admin(request: Request) -> str:
    settings = _settings(request)
    if not settings.admin_password:
        raise HTTPException(status_code=404)      # admin disabled: don't advertise it
    ip = client_ip(request, settings)
    if rate_remaining(settings, "admin_fail_ip", ip, MAX_FAILED_LOGINS_PER_HOUR, 3600) <= 0:
        raise HTTPException(status_code=429)
    creds = _basic_credentials(request)
    if creds is not None:
        # Evaluate both comparisons every time so timing doesn't reveal which one failed.
        user_ok = secrets.compare_digest(creds[0].encode(), settings.admin_user.encode())
        pass_ok = secrets.compare_digest(creds[1].encode(), settings.admin_password.encode())
        if user_ok and pass_ok:
            return creds[0]
        record_event(settings, "admin_fail_ip", ip)
        log.warning("Failed admin login attempt")
    raise HTTPException(status_code=401, headers=REALM_HEADER)


router = APIRouter(dependencies=[Depends(require_admin)], include_in_schema=False)


def _render(request: Request, template: str, **context) -> HTMLResponse:
    ctx = {"settings": _settings(request), "session": None, "csrf": "", "flash": None,
           "admin": True, "year": datetime.now(timezone.utc).year, **context}
    return request.app.state.templates.TemplateResponse(
        request, template, ctx, headers={"X-Robots-Tag": "noindex, nofollow"})


# ----------------------------------------------------------------------------
# Queries
# ----------------------------------------------------------------------------

SUBSCRIBERS_SQL = """
SELECT s.id, s.email, s.created_at, s.verified_at, s.newsletter_status,
       s.utm_source, s.utm_medium, s.utm_campaign, s.referrer,
       (SELECT COUNT(*) FROM jobs j WHERE j.subscriber_id = s.id) AS jobs_count
FROM subscribers s
ORDER BY s.created_at DESC, s.id DESC
"""

# One row per live (not deleted) screening by a verified subscriber, newest first. Staff
# follow-up is a per-report opt-in (jobs.followup_consent); followup_since is when the
# current choice was recorded in the consent ledger.
LEADS_BASE_SQL = """
SELECT s.id AS subscriber_id, s.email, s.newsletter_status, s.utm_source, s.utm_medium, s.utm_campaign,
       j.created_at AS job_created_at, j.status AS job_status, j.followup_consent,
       j.scheme, j.stage, j.site_label,
       j.state, j.district, j.total_area_ha, j.kpkt_class1_pct, j.centroid_lat, j.centroid_lon, j.notes,
       (SELECT c.created_at FROM consents c
         WHERE c.job_id = j.id AND c.purpose = 'site_followup' ORDER BY c.id DESC LIMIT 1) AS followup_since,
       (SELECT c.notice_version FROM consents c
         WHERE c.job_id = j.id AND c.purpose = 'site_followup' ORDER BY c.id DESC LIMIT 1)
         AS followup_notice_version,
       (SELECT COUNT(*) FROM jobs x WHERE x.subscriber_id = s.id AND x.status != 'deleted') AS jobs_count
FROM jobs j
JOIN subscribers s ON s.id = j.subscriber_id
WHERE s.verified_at IS NOT NULL AND j.status != 'deleted' {extra}
ORDER BY j.created_at DESC, j.id DESC
"""
LEADS_SQL = LEADS_BASE_SQL.format(extra="")
# The CSV handed to staff for outreach: ONLY screenings whose follow-up consent is granted now.
LEADS_EXPORT_SQL = LEADS_BASE_SQL.format(extra="AND j.followup_consent = 1")

CHANNELS_SQL = """
SELECT COALESCE(NULLIF(s.utm_source, ''), '(none)') AS source,
       COUNT(*) AS subscribers,
       SUM(CASE WHEN s.verified_at IS NOT NULL THEN 1 ELSE 0 END) AS verified,
       SUM(CASE WHEN EXISTS (SELECT 1 FROM jobs j WHERE j.subscriber_id = s.id) THEN 1 ELSE 0 END) AS with_jobs,
       SUM(CASE WHEN s.newsletter_status = 'subscribed' THEN 1 ELSE 0 END) AS newsletter,
       SUM(CASE WHEN EXISTS (SELECT 1 FROM jobs j WHERE j.subscriber_id = s.id AND j.status != 'deleted'
                              AND j.followup_consent = 1) THEN 1 ELSE 0 END) AS followup
FROM subscribers s
GROUP BY source
ORDER BY subscribers DESC, source
"""

NEWSLETTER_SQL = """
SELECT s.id, s.email, s.verified_at, s.utm_source, s.utm_medium, s.utm_campaign,
       (SELECT MAX(c.created_at) FROM consents c
         WHERE c.subscriber_id = s.id AND c.purpose = 'newsletter' AND c.action = 'confirmed') AS confirmed_at,
       (SELECT c.notice_version FROM consents c
         WHERE c.subscriber_id = s.id AND c.purpose = 'newsletter' AND c.action = 'confirmed'
         ORDER BY c.id DESC LIMIT 1) AS notice_version
FROM subscribers s
WHERE s.newsletter_status = 'subscribed'
ORDER BY s.email
"""


def _rows(settings: Settings, sql: str) -> list[dict]:
    with db(settings.db_path) as conn:
        return [dict(r) for r in conn.execute(sql)]


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------


@router.get("", include_in_schema=False)
@router.get("/", response_class=HTMLResponse)
def overview(request: Request):
    settings = _settings(request)
    channels = _rows(settings, CHANNELS_SQL)
    totals = {k: sum(c[k] or 0 for c in channels)
              for k in ("subscribers", "verified", "with_jobs", "followup", "newsletter")}
    return _render(request, "admin/overview.html", channels=channels, totals=totals)


@router.get("/subscribers", response_class=HTMLResponse)
def subscribers(request: Request):
    settings = _settings(request)
    return _render(request, "admin/subscribers.html", rows=_rows(settings, SUBSCRIBERS_SQL),
                   channels=_rows(settings, CHANNELS_SQL))


@router.get("/leads", response_class=HTMLResponse)
def leads(request: Request):
    return _render(request, "admin/leads.html", rows=_rows(_settings(request), LEADS_SQL))


# ----------------------------------------------------------------------------
# CSV exports
# ----------------------------------------------------------------------------


def csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection in user-supplied cells."""
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


def _csv_response(filename: str, header: list[str], rows: list[list]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_safe(v) for v in row])
    # UTF-8 BOM so Excel opens non-ASCII names correctly.
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/newsletter.csv")
def export_newsletter(request: Request):
    settings = _settings(request)
    rows = _rows(settings, NEWSLETTER_SQL)
    stamp = now_iso()[:10]
    return _csv_response(
        f"newsletter-{stamp}.csv",
        ["email", "confirmed_at", "notice_version", "utm_source", "utm_medium", "utm_campaign",
         "unsubscribe_url"],
        [[r["email"], r["confirmed_at"] or r["verified_at"], r["notice_version"], r["utm_source"],
          r["utm_medium"], r["utm_campaign"], unsubscribe_url(settings, r["id"])] for r in rows],
    )


@router.get("/export/leads.csv")
def export_leads(request: Request):
    """Screenings whose staff follow-up consent is currently granted, and nothing else."""
    rows = _rows(_settings(request), LEADS_EXPORT_SQL)
    stamp = now_iso()[:10]
    return _csv_response(
        f"leads-followup-{stamp}.csv",
        ["email", "job_created_at", "job_status", "followup_granted_at", "followup_notice_version",
         "scheme", "stage", "site_label", "state", "district", "total_area_ha", "kpkt_class1_pct",
         "centroid_lat", "centroid_lon", "notes", "newsletter_status", "utm_source", "utm_medium",
         "utm_campaign"],
        [[r["email"], r["job_created_at"], r["job_status"], r["followup_since"], r["followup_notice_version"],
          r["scheme"], r["stage"], r["site_label"], r["state"], r["district"], r["total_area_ha"],
          r["kpkt_class1_pct"], r["centroid_lat"], r["centroid_lon"], r["notes"], r["newsletter_status"],
          r["utm_source"], r["utm_medium"], r["utm_campaign"]] for r in rows],
    )

