"""FastAPI application factory and every visitor-facing route.

Flow (see docs/ARCHITECTURE.md): landing → POST /request-link → email → GET /start
(Continue button, does not consume) → POST /start (consumes, verifies, session) →
/upload → job → /reports/{id}. Plus account self-service, unsubscribe, privacy
notice and the development outbox.

Handlers that parse a form are async (form parsing must be awaited) and hand the
blocking work (SQLite, SMTP, file IO) to the threadpool; plain GET handlers are
sync and run in the threadpool automatically.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import secrets
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import jobs
from .admin import router as admin_router
from .config import APP_ROOT, Settings, get_settings
from .db import db, init_db, now_iso, parse_iso, tx
from .mailer import send_magic_link_email
from .security import (
    BodyTooLarge, InvalidEmail, SecurityMiddleware, Session, clear_session_cookie, client_ip,
    consume_token, create_magic_token, create_session, destroy_session, email_hash,
    is_disposable, load_session, magic_link, normalise_email, origin_of, peek_token,
    preauth_cookie_name, rate_limit, rate_limit_all, rate_remaining, safe_next_path,
    set_preauth_cookie, set_session_cookie, tokens_equal, turnstile_enabled,
    verify_csrf, verify_turnstile, verify_unsubscribe_token,
)

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Vocabulary shared by templates, validation and exports
# ----------------------------------------------------------------------------

SCHEMES = {
    "lss": "Large Scale Solar (LSS)",
    "cress": "CRESS",
    "fpv": "Floating solar (FPV)",
    "rooftop": "Rooftop / self-consumption",
    "other": "Other",
}
STAGES = {
    "exploring": "Exploring options",
    "land_secured": "Land secured / under negotiation",
    "bidding": "Preparing a bid or submission",
    "other": "Other",
}
FIGURE_FILES = ("1_site_layout.png", "2_elevation.png", "3_slope_classes.png", "4_profiles.png")
SLOPE_BINS = ("0-2", "2-5", "5-10", "10-15", "15-25", "25-35", ">35")
KPKT_CLASSES = ("I", "II", "III", "IV")
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign")
MAX_LABEL_CHARS = 120
MAX_NOTES_CHARS = 500
MYT = timezone(timedelta(hours=8), "MYT")     # Malaysia has no daylight saving

# The exact wording shown next to each consent, as (English, Bahasa Malaysia). The
# consent ledger stores consent_wording(key), i.e. both lines exactly as displayed.
CONSENT = {
    "service": ("Your email is required so we can send your access link and report.",
                "E-mel anda diperlukan untuk menghantar pautan akses dan laporan anda."),
    "site_followup": ("EcoEnergy may follow up with you about the site you submit.",
                      "EcoEnergy mungkin menghubungi anda berkenaan tapak yang anda hantar."),
    "newsletter": ("Also send me EcoEnergy's solar policy and scheme insights by email (optional). "
                   "Unsubscribe any time.",
                   "Hantar juga kepada saya pandangan dasar dan skim solar EcoEnergy melalui e-mel "
                   "(pilihan). Berhenti melanggan bila-bila masa."),
    "newsletter_account": ("Send me EcoEnergy's solar policy and scheme insights by email. "
                           "Unsubscribe any time.",
                           "Hantar kepada saya pandangan dasar dan skim solar EcoEnergy melalui e-mel. "
                           "Berhenti melanggan bila-bila masa."),
    "newsletter_off_account": ("Unsubscribe me from EcoEnergy's insights emails.",
                               "Berhentikan langganan e-mel pandangan EcoEnergy saya."),
    "newsletter_off_link": ("Unsubscribe me from EcoEnergy's insights emails.",
                            "Berhentikan langganan e-mel pandangan EcoEnergy saya."),
}


def consent_wording(key: str) -> str:
    en, bm = CONSENT[key]
    return f"{en} / {bm}"


MESSAGES = {
    "login": ("info", "Please request a fresh link to continue. Links and sessions expire "
                      "to keep your site data safe."),
    "logged_out": ("info", "You have been logged out."),
    "deleted": ("success", "Your report, site file and results have been deleted."),
    "newsletter_on": ("success", "You are subscribed to EcoEnergy insights. You can unsubscribe any time."),
    "newsletter_off": ("success", "You have been unsubscribed from EcoEnergy insights."),
}

GENERIC_UPLOAD_ERROR = ("We couldn't read that file. Please check it opens in Google Earth "
                        "and try again.")


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------


def fmt_num(value: Any, digits: int = 1, unit: str = "") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value) \
            or math.isinf(value):
        return "—"
    text = f"{value:,.{digits}f}"
    return f"{text} {unit}" if unit else text


def fmt_dt(value: str | None, with_time: bool = True) -> str:
    if not value:
        return "—"
    try:
        dt = parse_iso(value).astimezone(MYT)
    except (TypeError, ValueError):
        return "—"
    return dt.strftime("%d %b %Y, %H:%M MYT" if with_time else "%d %b %Y").lstrip("0")


def linkify(text: str | None) -> Markup:
    """Escape plain text and make http(s) URLs clickable (dev outbox only)."""
    escaped = str(escape(text or ""))
    return Markup(re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', escaped))


def clean_utm(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[^\w.\-+% ]", "", value.strip())[:100].strip()
    return cleaned or None


def clean_text(value: Any) -> str:
    """Strip control characters (keep newlines) and surrounding whitespace."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", "", value.replace("\r\n", "\n")).strip()


def clean_filename(name: str) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[-200:] or "upload"


def referer_origin(request: Request, settings: Settings) -> str | None:
    """Origin of an external Referer (e.g. https://www.linkedin.com); never path or query."""
    origin = origin_of(request.headers.get("referer", ""))
    if not origin or origin == origin_of(settings.base_url):
        return None
    return origin[:200]


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


def current_session(request: Request) -> Session | None:
    if not hasattr(request.state, "tt_session"):
        request.state.tt_session = load_session(settings_of(request), request)
    return request.state.tt_session


def render(request: Request, template: str, status_code: int = 200,
           headers: dict[str, str] | None = None, **context: Any) -> HTMLResponse:
    settings = settings_of(request)
    session = current_session(request)
    code = request.query_params.get("m")
    ctx = {
        "settings": settings,
        "session": session,
        "csrf": session.csrf if session else "",
        "flash": MESSAGES.get(code) if code else None,
        "year": datetime.now(MYT).year,
        "dev_outbox": settings.is_dev and settings.mail_backend == "outbox",
        **context,
    }
    return request.app.state.templates.TemplateResponse(
        request, template, ctx, status_code=status_code, headers=headers)


def login_redirect() -> RedirectResponse:
    return RedirectResponse("/?m=login", status_code=303)


async def read_form(request: Request) -> dict[str, str]:
    """Small url-encoded forms only; files are refused."""
    form = await request.form(max_files=0, max_fields=30)
    return {k: v for k, v in form.items() if isinstance(v, str)}


def require_csrf(session: Session | None, form: dict[str, Any]) -> None:
    if not verify_csrf(session, form.get("csrf")):
        raise HTTPException(status_code=403, detail="csrf")


def add_consent(conn, subscriber_id: int, purpose: str, action: str, wording: str,
                notice_version: str, ip: str | None, user_agent: str | None) -> None:
    conn.execute(
        "INSERT INTO consents (subscriber_id, purpose, action, notice_version, wording, ip, "
        "user_agent, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (subscriber_id, purpose, action, notice_version, wording, ip, (user_agent or "")[:300] or None,
         now_iso()),
    )


def owned_job(settings: Settings, session: Session, job_id: str) -> dict | None:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{8,64}", job_id or ""):
        return None
    with db(settings.db_path) as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND subscriber_id = ? AND status != 'deleted'",
            (job_id, session.subscriber_id),
        ).fetchone()
    return dict(row) if row else None


def load_result(settings: Settings, job_id: str) -> dict | None:
    path = jobs.job_dir(settings, job_id) / "result.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summarise_result(result: dict) -> dict:
    """Numbers for the "At a glance" tiles, tolerant of missing values."""
    sites = result.get("sites") or []

    def values(key: str) -> list[float]:
        return [s[key] for s in sites if isinstance(s.get(key), (int, float))]

    mins, maxs, slopes = values("elev_min_m"), values("elev_max_m"), values("slope_max_deg")
    return {
        "total_area_ha": (result.get("totals") or {}).get("total_area_ha"),
        "elev_min": min(mins) if mins else None,
        "elev_max": max(maxs) if maxs else None,
        "class1_pct": (result.get("kpkt_overall_pct") or {}).get("I"),
        "slope_max": max(slopes) if slopes else None,
    }


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(APP_ROOT / "templates"))
    env = templates.env
    env.filters.update(num=fmt_num, dt=fmt_dt, linkify=linkify)
    env.globals.update(SCHEMES=SCHEMES, STAGES=STAGES, CONSENT=CONSENT,
                       SLOPE_BINS=SLOPE_BINS, KPKT_CLASSES=KPKT_CLASSES)
    return templates


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"status": "ok"}


# --- landing and link request ------------------------------------------------


def landing_response(request: Request, *, email: str = "", newsletter: bool = False,
                     utm: dict | None = None, ref: str | None = None, error: str | None = None,
                     status_code: int = 200) -> HTMLResponse:
    return render(request, "landing.html", status_code=status_code, email=email,
                  newsletter=newsletter, utm=utm or {}, ref=ref or "", error=error,
                  turnstile=turnstile_enabled(settings_of(request)))


@router.get("/", response_class=HTMLResponse)
def landing(request: Request):
    settings = settings_of(request)
    utm = {k: clean_utm(request.query_params.get(k)) for k in UTM_KEYS}
    return landing_response(request, utm=utm, ref=referer_origin(request, settings))


@router.post("/request-link", response_class=HTMLResponse)
async def request_link(request: Request):
    form = await read_form(request)
    return await run_in_threadpool(_request_link, request, form)


def _request_link(request: Request, form: dict[str, str]) -> HTMLResponse:
    settings = settings_of(request)
    utm = {k: clean_utm(form.get(k)) for k in UTM_KEYS}
    ref_origin = origin_of(form.get("ref", ""))[:200] or None
    newsletter = form.get("newsletter") == "yes"
    raw_email = (form.get("email") or "").strip()[:254]

    def form_error(message: str) -> HTMLResponse:
        return landing_response(request, email=raw_email, newsletter=newsletter, utm=utm,
                                ref=ref_origin, error=message, status_code=400)

    try:
        email = normalise_email(raw_email)
    except InvalidEmail as exc:
        return form_error(str(exc))
    if is_disposable(email):
        return form_error("Please use a permanent email address. Disposable inboxes can't "
                          "reliably receive your report.")

    ip = client_ip(request, settings)
    if not verify_turnstile(settings, form.get("cf-turnstile-response"), ip):
        return form_error("Please complete the quick human check and try again.")

    # From here on every outcome renders the same page, so the response never reveals
    # whether an address is known, suppressed or rate-limited.
    if rate_limit_all(settings, [("link_ip", ip, settings.rate_link_per_ip_hour, 3600),
                                 ("link_email", email, settings.rate_link_per_email_hour, 3600)]):
        try:
            raw = register_link_request(settings, email, newsletter, utm, ref_origin, ip,
                                        request.headers.get("user-agent"))
            send_magic_link_email(settings, email, magic_link(settings, raw))
        except Exception:
            log.exception("Link request could not be completed")
    else:
        log.info("Link request rate-limited")
    return render(request, "check_inbox.html", email=email)


def register_link_request(settings: Settings, email: str, newsletter: bool, utm: dict,
                          referrer: str | None, ip: str, user_agent: str | None) -> str:
    """Upsert the subscriber, append consent rows and return a fresh raw magic token."""
    version = settings.notice_version
    with tx(settings.db_path) as conn:
        # Submitting again after erasure is a new, active sign-up: lift the suppression.
        conn.execute("DELETE FROM suppression WHERE email_sha256 = ?", (email_hash(email),))
        conn.execute(
            "INSERT INTO subscribers (email, created_at, utm_source, utm_medium, utm_campaign, referrer) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(email) DO NOTHING",
            (email, now_iso(), utm.get("utm_source"), utm.get("utm_medium"),
             utm.get("utm_campaign"), referrer),
        )
        sub = conn.execute("SELECT id, newsletter_status FROM subscribers WHERE email = ?",
                           (email,)).fetchone()
        for purpose in ("service", "site_followup"):
            add_consent(conn, sub["id"], purpose, "granted", consent_wording(purpose), version, ip, user_agent)
        if newsletter:
            add_consent(conn, sub["id"], "newsletter", "granted", consent_wording("newsletter"), version,
                        ip, user_agent)
            if sub["newsletter_status"] != "subscribed":
                conn.execute("UPDATE subscribers SET newsletter_status = 'pending' WHERE id = ?",
                             (sub["id"],))
        return create_magic_token(settings, sub["id"], conn=conn)


# --- magic link confirmation ---------------------------------------------------


def start_response(request: Request, token: str, notice: str | None = None) -> HTMLResponse:
    settings = settings_of(request)
    valid = peek_token(settings, token) is not None
    pre = request.cookies.get(preauth_cookie_name(settings), "")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{16,64}", pre):
        pre = secrets.token_urlsafe(24)
    response = render(request, "start.html", status_code=200 if valid else 400,
                      valid=valid, token=token if valid else "", pre=pre, notice=notice)
    if valid:
        set_preauth_cookie(response, settings, pre)
    return response


@router.get("/start", response_class=HTMLResponse)
def start_page(request: Request, t: str = ""):
    # Deliberately read-only: link scanners (e.g. Safe Links) prefetch this URL.
    return start_response(request, t[:128])


@router.post("/start")
async def start_confirm(request: Request):
    form = await read_form(request)
    return await run_in_threadpool(_start_confirm, request, form)


def _start_confirm(request: Request, form: dict[str, str]) -> Response:
    settings = settings_of(request)
    token = (form.get("t") or "")[:128]
    # Login-CSRF guard: the pre-auth cookie is SameSite=Strict, so a cross-site page cannot
    # submit someone else's token on the visitor's behalf.
    if not tokens_equal(form.get("pre"), request.cookies.get(preauth_cookie_name(settings))):
        return start_response(request, token, notice="Please press Continue once more.")

    ip = client_ip(request, settings)
    user_agent = request.headers.get("user-agent")
    with tx(settings.db_path) as conn:
        row = consume_token(settings, token, conn)
        if row is not None:
            subscriber_id = row["subscriber_id"]
            next_path = row["next_path"]
            confirm_subscriber(conn, subscriber_id, ip, user_agent)
            raw_session = create_session(settings, subscriber_id, conn=conn)
    if row is None:
        return render(request, "start.html", status_code=400, valid=False, token="", pre="",
                      notice=None)

    destroy_session(settings, request)       # replace any previous session in this browser
    response = RedirectResponse(safe_next_path(next_path) or "/upload", status_code=303)
    set_session_cookie(response, settings, raw_session)
    response.delete_cookie(preauth_cookie_name(settings), path="/", secure=settings.secure_cookies,
                           httponly=True, samesite="strict")
    return response


def confirm_subscriber(conn, subscriber_id: int, ip: str, user_agent: str | None) -> None:
    """Mark the address verified and confirm every consent whose latest action is 'granted'
    (double opt-in: a pending newsletter becomes 'subscribed' only here)."""
    sub = conn.execute("SELECT verified_at, newsletter_status FROM subscribers WHERE id = ?",
                       (subscriber_id,)).fetchone()
    if sub["verified_at"] is None:
        conn.execute("UPDATE subscribers SET verified_at = ? WHERE id = ?", (now_iso(), subscriber_id))
    latest = conn.execute(
        "SELECT * FROM consents WHERE id IN "
        "(SELECT MAX(id) FROM consents WHERE subscriber_id = ? GROUP BY purpose)",
        (subscriber_id,),
    ).fetchall()
    for c in latest:
        if c["action"] == "granted":
            add_consent(conn, subscriber_id, c["purpose"], "confirmed", c["wording"], c["notice_version"],
                        ip, user_agent)
    if sub["newsletter_status"] == "pending":
        conn.execute("UPDATE subscribers SET newsletter_status = 'subscribed' WHERE id = ?",
                     (subscriber_id,))


# --- upload --------------------------------------------------------------------


def runs_left(settings: Settings, session: Session, ip: str) -> int:
    return min(
        rate_remaining(settings, "job_email", session.email, settings.rate_jobs_per_email_day, 86400),
        rate_remaining(settings, "job_ip", ip, settings.rate_jobs_per_ip_day, 86400),
    )


def upload_response(request: Request, session: Session, *, error: str | None = None,
                    values: dict | None = None, status_code: int = 200) -> HTMLResponse:
    settings = settings_of(request)
    return render(request, "upload.html", status_code=status_code, error=error, values=values or {},
                  runs_left=runs_left(settings, session, client_ip(request, settings)),
                  max_mb=fmt_num(settings.max_upload_mb, 0), max_label=MAX_LABEL_CHARS,
                  max_notes=MAX_NOTES_CHARS)


@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    session = current_session(request)
    if session is None:
        return login_redirect()
    return upload_response(request, session)


@router.post("/upload")
async def upload_submit(request: Request):
    settings = settings_of(request)
    session = await run_in_threadpool(current_session, request)
    if session is None:
        return login_redirect()
    try:
        form = await request.form(max_files=1, max_fields=20)
    except BodyTooLarge:
        return await run_in_threadpool(
            upload_response, request, session, status_code=413,
            error=f"That file is larger than {fmt_num(settings.max_upload_mb, 0)} MB. "
                  "Please upload a smaller KML/KMZ (just the site boundaries and routes).")
    try:
        return await run_in_threadpool(_upload_submit, request, session, form)
    finally:
        await form.close()


def _copy_limited(src, dest: Path, limit: int) -> tuple[int, str] | None:
    """Stream ``src`` to ``dest``; None if it exceeds ``limit`` bytes. Returns (size, sha256)."""
    digest = hashlib.sha256()
    size = 0
    src.seek(0)
    with open(dest, "wb") as out:
        while chunk := src.read(64 * 1024):
            size += len(chunk)
            if size > limit:
                return None
            digest.update(chunk)
            out.write(chunk)
    return size, digest.hexdigest()


def _upload_submit(request: Request, session: Session, form) -> Response:
    settings = settings_of(request)
    require_csrf(session, form)
    values = {
        "site_label": clean_text(form.get("site_label")),
        "scheme": form.get("scheme") if form.get("scheme") in SCHEMES else "",
        "stage": form.get("stage") if form.get("stage") in STAGES else "",
        "notes": clean_text(form.get("notes")),
    }

    def fail(message: str, status_code: int = 400) -> HTMLResponse:
        return upload_response(request, session, error=message, values=values, status_code=status_code)

    if len(values["site_label"]) > MAX_LABEL_CHARS:
        return fail(f"Please keep the site label to {MAX_LABEL_CHARS} characters or fewer.")
    if len(values["notes"]) > MAX_NOTES_CHARS:
        return fail(f"Please keep your notes to {MAX_NOTES_CHARS} characters or fewer.")
    upload = form.get("kml_file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return fail("Please choose a .kml or .kmz file to upload.")
    filename = clean_filename(upload.filename)
    ext = Path(filename).suffix.lower()
    if ext not in {".kml", ".kmz"}:
        return fail("Please upload a .kml or .kmz file (for example, exported from Google Earth).")

    ip = client_ip(request, settings)
    limit_msg = (f"You've reached today's limit of {settings.rate_jobs_per_email_day} screenings. "
                 "Please try again tomorrow, or contact us for a full study.")
    if runs_left(settings, session, ip) <= 0:
        return fail(limit_msg, 429)
    # Invalid files don't use up a run, but attempts themselves are capped per IP.
    if not rate_limit(settings, "upload_attempt_ip", ip, max(20, settings.rate_jobs_per_ip_day * 3), 86400):
        return fail(limit_msg, 429)

    job_id = secrets.token_urlsafe(16)
    job_path = jobs.job_dir(settings, job_id)
    job_path.mkdir(parents=True)
    dest = job_path / f"input{ext}"
    try:
        copied = _copy_limited(upload.file, dest, settings.max_upload_bytes)
        if copied is None:
            return fail(f"That file is larger than {fmt_num(settings.max_upload_mb, 0)} MB. Please "
                        "upload a smaller KML/KMZ (just the site boundaries and routes).", 413)
        size, sha = copied
        if size == 0:
            return fail("That file is empty. Please choose your exported .kml or .kmz file.")
        try:
            from app.terrain import ScreeningError, validate_upload
        except Exception:
            log.exception("Terrain engine unavailable")
            return fail("The screening service is temporarily unavailable. Please try again shortly.", 503)
        try:
            validate_upload(dest, settings, filename)
        except ScreeningError as exc:
            return fail(str(exc) or GENERIC_UPLOAD_ERROR)
        except Exception:
            log.exception("validate_upload crashed")
            return fail(GENERIC_UPLOAD_ERROR)
        # The run is only charged once the file is known to be valid.
        if not rate_limit_all(settings, [
            ("job_email", session.email, settings.rate_jobs_per_email_day, 86400),
            ("job_ip", ip, settings.rate_jobs_per_ip_day, 86400),
        ]):
            return fail(limit_msg, 429)
        jobs.enqueue_job(settings, job_id, session.subscriber_id, input_filename=filename,
                         input_sha256=sha, site_label=values["site_label"] or None,
                         scheme=values["scheme"] or None, stage=values["stage"] or None,
                         notes=values["notes"] or None)
        job_path = None          # committed: keep the files
    finally:
        if job_path is not None:
            shutil.rmtree(job_path, ignore_errors=True)
    return RedirectResponse(f"/reports/{job_id}", status_code=303)


# --- reports -------------------------------------------------------------------


@router.get("/reports", response_class=HTMLResponse)
def reports_list(request: Request):
    session = current_session(request)
    if session is None:
        return login_redirect()
    with db(settings_of(request).db_path) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM jobs WHERE subscriber_id = ? AND status != 'deleted' ORDER BY created_at DESC",
            (session.subscriber_id,))]
    return render(request, "reports.html", jobs=rows)


@router.get("/reports/{job_id}", response_class=HTMLResponse)
def report_page(request: Request, job_id: str):
    settings = settings_of(request)
    session = current_session(request)
    if session is None:
        return login_redirect()
    job = owned_job(settings, session, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    if job["status"] in {"queued", "running"}:
        return render(request, "report_status.html", job=job)
    if job["status"] == "failed":
        return render(request, "report_failed.html", job=job, error=job["error"] or jobs.GENERIC_FAILURE)
    result = load_result(settings, job_id)
    if result is None:
        log.error("Job %s is done but result.json is missing or unreadable", job_id)
        return render(request, "report_failed.html", job=job, error=jobs.GENERIC_FAILURE)
    figures = [f for f in (result.get("figures") or [])
               if isinstance(f, dict) and f.get("file") in FIGURE_FILES]
    consult = f"{settings.consult_url}{'&' if '?' in settings.consult_url else '?'}" \
              "utm_source=terrain_tool&utm_medium=report"
    return render(request, "report_result.html", job=job, result=result, figures=figures,
                  glance=summarise_result(result), consult_link=consult,
                  label=job["site_label"] or (result.get("meta") or {}).get("site_label")
                  or job["input_filename"] or "Your site")


@router.get("/api/reports/{job_id}/status")
def report_status_api(request: Request, job_id: str):
    settings = settings_of(request)
    session = current_session(request)
    job = owned_job(settings, session, job_id) if session else None
    if job is None:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return JSONResponse({"status": job["status"], "error": job["error"]})


def _owned_done_file(request: Request, job_id: str, name: str) -> Path:
    settings = settings_of(request)
    session = current_session(request)
    job = owned_job(settings, session, job_id) if session else None
    path = jobs.job_dir(settings, job_id) / name
    if job is None or job["status"] != "done" or not path.is_file():
        raise HTTPException(status_code=404)
    return path


@router.get("/reports/{job_id}/files/{name}")
def report_file(request: Request, job_id: str, name: str):
    if name not in FIGURE_FILES:
        raise HTTPException(status_code=404)
    path = _owned_done_file(request, job_id, name)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.get("/reports/{job_id}/download.pdf")
def download_pdf(request: Request, job_id: str):
    path = _owned_done_file(request, job_id, "report.pdf")
    return FileResponse(path, media_type="application/pdf", filename=f"terrain-screening-{job_id[:8]}.pdf",
                        headers={"Cache-Control": "private, no-store"})


@router.get("/reports/{job_id}/download.docx")
def download_docx(request: Request, job_id: str):
    path = _owned_done_file(request, job_id, "report.docx")
    return FileResponse(
        path, filename=f"terrain-screening-{job_id[:8]}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Cache-Control": "private, no-store"})


@router.post("/reports/{job_id}/delete")
async def report_delete(request: Request, job_id: str):
    form = await read_form(request)
    return await run_in_threadpool(_report_delete, request, job_id, form)


def _report_delete(request: Request, job_id: str, form: dict[str, str]) -> Response:
    settings = settings_of(request)
    session = current_session(request)
    if session is None:
        return login_redirect()
    require_csrf(session, form)
    if owned_job(settings, session, job_id) is None:
        raise HTTPException(status_code=404)
    jobs.delete_job_data(settings, job_id)
    log.info("Job %s deleted by its owner", job_id)
    return RedirectResponse("/reports?m=deleted", status_code=303)


# --- account -------------------------------------------------------------------


def subscriber_data(settings: Settings, subscriber_id: int) -> dict:
    with db(settings.db_path) as conn:
        sub = dict(conn.execute("SELECT * FROM subscribers WHERE id = ?", (subscriber_id,)).fetchone())
        consents = [dict(r) for r in conn.execute(
            "SELECT purpose, action, notice_version, wording, ip, user_agent, created_at "
            "FROM consents WHERE subscriber_id = ? ORDER BY id", (subscriber_id,))]
        job_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM jobs WHERE subscriber_id = ? ORDER BY created_at DESC", (subscriber_id,))]
    return {"subscriber": sub, "consents": consents, "jobs": job_rows}


@router.get("/account", response_class=HTMLResponse)
def account_page(request: Request):
    session = current_session(request)
    if session is None:
        return login_redirect()
    data = subscriber_data(settings_of(request), session.subscriber_id)
    return render(request, "account.html", **data)


@router.get("/account/export.json")
def account_export(request: Request):
    settings = settings_of(request)
    session = current_session(request)
    if session is None:
        return login_redirect()
    data = subscriber_data(settings, session.subscriber_id)
    for job in data["jobs"]:
        job["result"] = load_result(settings, job["id"]) if job["status"] == "done" else None
    payload = {
        "exported_at": now_iso(),
        "controller": "EcoEnergy Consultancy Sdn. Bhd. (contact@ecoconsultancy.services)",
        "notice_version": settings.notice_version,
        **data,
    }
    return Response(json.dumps(payload, indent=2, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="terrain-tool-my-data.json"'})


@router.post("/account/newsletter")
async def account_newsletter(request: Request):
    form = await read_form(request)
    return await run_in_threadpool(_account_newsletter, request, form)


def _account_newsletter(request: Request, form: dict[str, str]) -> Response:
    settings = settings_of(request)
    session = current_session(request)
    if session is None:
        return login_redirect()
    require_csrf(session, form)
    ip = client_ip(request, settings)
    user_agent = request.headers.get("user-agent")
    version = settings.notice_version
    action = form.get("action")
    with tx(settings.db_path) as conn:
        sub = conn.execute("SELECT verified_at, newsletter_status FROM subscribers WHERE id = ?",
                           (session.subscriber_id,)).fetchone()
        if action == "subscribe" and sub["newsletter_status"] != "subscribed":
            wording = consent_wording("newsletter_account")
            add_consent(conn, session.subscriber_id, "newsletter", "granted", wording, version, ip, user_agent)
            # A session only exists for a verified address, so this is already double opt-in.
            if sub["verified_at"]:
                add_consent(conn, session.subscriber_id, "newsletter", "confirmed", wording, version, ip,
                            user_agent)
            conn.execute("UPDATE subscribers SET newsletter_status = ? WHERE id = ?",
                         ("subscribed" if sub["verified_at"] else "pending", session.subscriber_id))
        elif action == "unsubscribe" and sub["newsletter_status"] in {"pending", "subscribed"}:
            add_consent(conn, session.subscriber_id, "newsletter", "withdrawn",
                        consent_wording("newsletter_off_account"), version, ip, user_agent)
            conn.execute("UPDATE subscribers SET newsletter_status = 'unsubscribed' WHERE id = ?",
                         (session.subscriber_id,))
    code = "newsletter_on" if action == "subscribe" else "newsletter_off"
    return RedirectResponse(f"/account?m={code}", status_code=303)


def erase_subscriber(settings: Settings, subscriber_id: int) -> None:
    """Right to erasure: files, rows (cascade) and a suppression entry for sha256(email)."""
    with tx(settings.db_path) as conn:
        sub = conn.execute("SELECT email FROM subscribers WHERE id = ?", (subscriber_id,)).fetchone()
        if sub is None:
            return
        job_ids = [r["id"] for r in conn.execute("SELECT id FROM jobs WHERE subscriber_id = ?",
                                                  (subscriber_id,))]
        conn.execute("INSERT INTO suppression (email_sha256, created_at) VALUES (?, ?) "
                     "ON CONFLICT(email_sha256) DO NOTHING", (email_hash(sub["email"]), now_iso()))
        conn.execute("DELETE FROM outbox WHERE to_addr = ?", (sub["email"],))
        conn.execute("DELETE FROM subscribers WHERE id = ?", (subscriber_id,))
    for job_id in job_ids:
        shutil.rmtree(jobs.job_dir(settings, job_id), ignore_errors=True)
    log.info("Subscriber %s erased on request (%d job(s))", subscriber_id, len(job_ids))


@router.post("/account/delete")
async def account_delete(request: Request):
    form = await read_form(request)
    return await run_in_threadpool(_account_delete, request, form)


def _account_delete(request: Request, form: dict[str, str]) -> Response:
    settings = settings_of(request)
    session = current_session(request)
    if session is None:
        return login_redirect()
    require_csrf(session, form)
    if form.get("confirm") != "yes":
        data = subscriber_data(settings, session.subscriber_id)
        return render(request, "account.html", status_code=400,
                      delete_error="Please tick the box to confirm you want everything deleted.", **data)
    erase_subscriber(settings, session.subscriber_id)
    request.state.tt_session = None
    response = render(request, "goodbye.html")
    clear_session_cookie(response, settings)
    return response


@router.post("/logout")
async def logout(request: Request):
    form = await read_form(request)
    return await run_in_threadpool(_logout, request, form)


def _logout(request: Request, form: dict[str, str]) -> Response:
    settings = settings_of(request)
    session = current_session(request)
    if session is not None:
        require_csrf(session, form)
        destroy_session(settings, request)
    response = RedirectResponse("/?m=logged_out", status_code=303)
    clear_session_cookie(response, settings)
    return response


# --- unsubscribe (works without a session; RFC 8058 one-click) -------------------


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(request: Request, u: str = ""):
    valid = verify_unsubscribe_token(settings_of(request), u) is not None
    return render(request, "unsubscribe.html", status_code=200 if valid else 400,
                  valid=valid, u=u if valid else "", done=False)


@router.post("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_submit(request: Request):
    form = await read_form(request)
    return await run_in_threadpool(_unsubscribe_submit, request, form)


def _unsubscribe_submit(request: Request, form: dict[str, str]) -> Response:
    settings = settings_of(request)
    value = request.query_params.get("u") or form.get("u") or ""
    subscriber_id = verify_unsubscribe_token(settings, value)
    if subscriber_id is None:
        return render(request, "unsubscribe.html", status_code=400, valid=False, u="", done=False)
    with tx(settings.db_path) as conn:
        sub = conn.execute("SELECT newsletter_status FROM subscribers WHERE id = ?",
                           (subscriber_id,)).fetchone()
        # Unknown (e.g. erased) subscribers get the same answer: nothing to reveal.
        if sub is not None and sub["newsletter_status"] != "unsubscribed":
            if sub["newsletter_status"] in {"pending", "subscribed"}:
                add_consent(conn, subscriber_id, "newsletter", "withdrawn", consent_wording("newsletter_off_link"),
                            settings.notice_version, client_ip(request, settings),
                            request.headers.get("user-agent"))
            conn.execute("UPDATE subscribers SET newsletter_status = 'unsubscribed' WHERE id = ?",
                         (subscriber_id,))
    return render(request, "unsubscribe.html", valid=True, u="", done=True)


# --- static pages ----------------------------------------------------------------


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return render(request, "privacy.html")


# --- development outbox ------------------------------------------------------------


def _require_dev_outbox(request: Request) -> Settings:
    settings = settings_of(request)
    if not (settings.is_dev and settings.mail_backend == "outbox"):
        raise HTTPException(status_code=404)
    return settings


@router.get("/dev/outbox", response_class=HTMLResponse)
def dev_outbox(request: Request):
    settings = _require_dev_outbox(request)
    with db(settings.db_path) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, to_addr, subject, created_at FROM outbox ORDER BY id DESC LIMIT 100")]
    return render(request, "dev_outbox.html", messages=rows)


def _outbox_message(settings: Settings, message_id: int) -> dict:
    with db(settings.db_path) as conn:
        row = conn.execute("SELECT * FROM outbox WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404)
    return dict(row)


@router.get("/dev/outbox/{message_id}", response_class=HTMLResponse)
def dev_outbox_message(request: Request, message_id: int):
    settings = _require_dev_outbox(request)
    msg = _outbox_message(settings, message_id)
    msg["headers"] = json.loads(msg.get("headers_json") or "{}")
    return render(request, "dev_outbox_message.html", msg=msg)


@router.get("/dev/outbox/{message_id}/html", response_class=HTMLResponse)
def dev_outbox_message_html(request: Request, message_id: int):
    settings = _require_dev_outbox(request)
    msg = _outbox_message(settings, message_id)
    if not msg.get("html_body"):
        raise HTTPException(status_code=404)
    return HTMLResponse(msg["html_body"])


# ----------------------------------------------------------------------------
# Error pages
# ----------------------------------------------------------------------------

ERROR_TEXT = {
    400: ("Something was wrong with that request", "Please go back and try again."),
    403: ("This form has expired", "For your security, forms are tied to your session. "
          "Go back, reload the page and try again."),
    404: ("Page not found", "The page doesn't exist, or it belongs to a different session. "
          "If you followed an email link, request a fresh one."),
    413: ("That upload is too large", "Please go back and choose a smaller file."),
    429: ("Too many requests", "Please wait a little and try again."),
    500: ("Something went wrong", "Our team has been notified. Please try again shortly."),
}


def error_page(request: Request, status_code: int, headers: dict | None = None) -> Response:
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": ERROR_TEXT.get(status_code, ERROR_TEXT[400])[0]},
                            status_code=status_code, headers=headers)
    title, body = ERROR_TEXT.get(status_code, ERROR_TEXT[500 if status_code >= 500 else 400])
    try:
        return render(request, "error.html", status_code=status_code, headers=headers,
                      title=title, body=body, code=status_code)
    except Exception:          # never let the error page itself fail
        log.exception("Error page rendering failed")
        return HTMLResponse(f"<h1>{escape(title)}</h1><p>{escape(body)}</p>", status_code=status_code,
                            headers=headers)


# ----------------------------------------------------------------------------
# App factory
# ----------------------------------------------------------------------------


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    init_db(settings.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker = jobs.Worker(settings) if settings.worker_inline else None
        app.state.worker = worker
        if worker:
            worker.start()
        try:
            yield
        finally:
            if worker:
                await run_in_threadpool(worker.stop)

    app = FastAPI(title="EcoEnergy Terrain Screening", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.templates = make_templates()
    app.state.worker = None

    app.add_middleware(SecurityMiddleware, settings=settings)
    app.mount("/static", StaticFiles(directory=str(APP_ROOT / "static")), name="static")
    app.include_router(admin_router, prefix="/admin")
    app.include_router(router)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return await run_in_threadpool(error_page, request, exc.status_code, exc.headers)

    @app.exception_handler(BodyTooLarge)
    async def too_large(request: Request, exc: BodyTooLarge):
        return await run_in_threadpool(error_page, request, 413)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        log.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return await run_in_threadpool(error_page, request, 500)

    return app
