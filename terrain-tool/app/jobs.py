"""Job queue on the ``jobs`` table: enqueue, atomic claim, processing, the inline
worker thread, and retention sweeps.

The terrain engine and report renderers are imported lazily inside
``process_job`` so the web app starts (and its tests run) independently of them.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import time
from datetime import timedelta
from pathlib import Path

from .config import Settings
from .db import db, iso, iso_in, now_iso, tx, utcnow
from .mailer import send_report_ready_email
from .security import create_magic_token, email_hash, magic_link

log = logging.getLogger(__name__)

GENERIC_FAILURE = ("Something went wrong while processing your site. "
                   "Our team has been notified.")
STALE_RUNNING_MINUTES = 15
SWEEP_INTERVAL_SECONDS = 600
EVENT_RETENTION_DAYS = 2
OUTBOX_RETENTION_DAYS = 7
ORPHAN_DIR_GRACE_SECONDS = 3600       # an upload creates its directory just before the job row

# Fields cleared whenever a job's site data is deleted (user "Delete now" or retention).
# The visitor's optional answers (label, scheme, stage, notes) go with the site they describe.
SITE_DATA_FIELDS = ("site_label", "scheme", "stage", "notes", "input_filename", "input_sha256",
                    "total_area_ha", "state", "district", "centroid_lat", "centroid_lon",
                    "kpkt_class1_pct")


def job_dir(settings: Settings, job_id: str) -> Path:
    return settings.jobs_dir / job_id


def input_path(settings: Settings, job_id: str) -> Path | None:
    for ext in (".kml", ".kmz"):
        p = job_dir(settings, job_id) / f"input{ext}"
        if p.is_file():
            return p
    return None


# ----------------------------------------------------------------------------
# Enqueue / claim
# ----------------------------------------------------------------------------


def enqueue_job(settings: Settings, job_id: str, subscriber_id: int, *, input_filename: str,
                input_sha256: str, site_label: str | None = None, scheme: str | None = None,
                stage: str | None = None, notes: str | None = None, followup_consent: bool = False,
                conn: sqlite3.Connection | None = None) -> None:
    """Insert a queued job; the input file must already be at {jobs_dir}/{job_id}/input.*

    Pass ``conn`` to insert inside the caller's transaction (the upload handler writes the
    job and its follow-up consent row atomically)."""
    sql = ("INSERT INTO jobs (id, subscriber_id, status, created_at, delete_after, input_filename, "
           "input_sha256, site_label, scheme, stage, notes, followup_consent) "
           "VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)")
    params = (job_id, subscriber_id, now_iso(), iso_in(days=settings.retention_days), input_filename,
              input_sha256, site_label, scheme, stage, notes, 1 if followup_consent else 0)
    if conn is not None:
        conn.execute(sql, params)
        return
    with db(settings.db_path) as own:
        own.execute(sql, params)


def claim_next(settings: Settings) -> dict | None:
    """Atomically move the oldest queued job to running and return it (or None).

    The guarded UPDATE inside an IMMEDIATE transaction means two workers can never
    claim the same row, even across processes sharing the database.
    """
    with tx(settings.db_path) as conn:
        row = conn.execute(
            "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at, id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        cur = conn.execute(
            "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
            (now_iso(), row["id"]),
        )
        if cur.rowcount != 1:
            return None
        return dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())


def recover_stale(settings: Settings, older_than_minutes: int | None = STALE_RUNNING_MINUTES) -> int:
    """Crash recovery: re-queue jobs stuck in 'running' for longer than the threshold.
    ``None`` re-queues every running job (worker start-up: with the single-instance design no
    other worker can own one, so any 'running' row was abandoned by a stopped process)."""
    with db(settings.db_path) as conn:
        if older_than_minutes is None:
            cur = conn.execute("UPDATE jobs SET status = 'queued', started_at = NULL WHERE status = 'running'")
        else:
            cutoff = iso(utcnow() - timedelta(minutes=older_than_minutes))
            cur = conn.execute(
                "UPDATE jobs SET status = 'queued', started_at = NULL "
                "WHERE status = 'running' AND (started_at IS NULL OR started_at < ?)",
                (cutoff,),
            )
    if cur.rowcount:
        log.warning("Re-queued %d stale running job(s)", cur.rowcount)
    return cur.rowcount


# ----------------------------------------------------------------------------
# Processing
# ----------------------------------------------------------------------------


def _finish(settings: Settings, job_id: str, **fields) -> bool:
    """Update a running job; False if it was deleted (or its account erased) meanwhile."""
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db(settings.db_path) as conn:
        cur = conn.execute(f"UPDATE jobs SET {cols} WHERE id = ? AND status = 'running'",
                           (*fields.values(), job_id))
    if cur.rowcount != 1:
        # The visitor pressed Delete (or erased the account) while we worked: drop any output.
        shutil.rmtree(job_dir(settings, job_id), ignore_errors=True)
        return False
    return True


def _fail(settings: Settings, job_id: str, message: str) -> str:
    ok = _finish(settings, job_id, status="failed", finished_at=now_iso(), error=message)
    return "failed" if ok else "deleted"


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def derived_fields(result: dict) -> dict:
    """Lead summary columns stored on the job row (cleared again on deletion)."""
    location = result.get("location") or {}
    totals = result.get("totals") or {}
    kpkt = result.get("kpkt_overall_pct") or {}
    return {
        "total_area_ha": _num(totals.get("total_area_ha")),
        "state": location.get("state") or None,
        "district": location.get("district") or None,
        "centroid_lat": _num(location.get("centroid_lat")),
        "centroid_lon": _num(location.get("centroid_lon")),
        "kpkt_class1_pct": _num(kpkt.get("I")),
    }


def process_job(settings: Settings, job_id: str) -> str:
    """Run the screening + reports for a claimed (running) job. Returns the final status."""
    with db(settings.db_path) as conn:
        job = conn.execute(
            "SELECT j.*, s.email FROM jobs j JOIN subscribers s ON s.id = j.subscriber_id WHERE j.id = ?",
            (job_id,),
        ).fetchone()
    if job is None:
        shutil.rmtree(job_dir(settings, job_id), ignore_errors=True)
        return "deleted"

    try:
        from app.reports import build_reports
        from app.terrain import ScreeningError, run_screening
    except Exception:
        log.exception("Terrain engine or report renderer could not be imported (job %s)", job_id)
        return _fail(settings, job_id, GENERIC_FAILURE)

    out_dir = job_dir(settings, job_id)
    src = input_path(settings, job_id)
    try:
        if src is None:
            raise ScreeningError("We could not find your uploaded file. Please upload it again.",
                                 code="input_missing")
        meta = {
            "report_id": job_id,
            "generated_at": now_iso(),
            "site_label": job["site_label"],
            "scheme": job["scheme"],
            "stage": job["stage"],
            "input_filename": job["input_filename"],
        }
        result = run_screening(src, out_dir, settings, meta)
        build_reports(result, out_dir, settings)
    except ScreeningError as exc:
        log.info("Job %s failed screening: %s", job_id, getattr(exc, "code", "screening_error"))
        return _fail(settings, job_id, str(exc) or GENERIC_FAILURE)
    except Exception:
        log.exception("Job %s crashed", job_id)
        return _fail(settings, job_id, GENERIC_FAILURE)

    if not _finish(settings, job_id, status="done", finished_at=now_iso(), error=None,
                   **derived_fields(result)):
        return "deleted"

    try:
        raw = create_magic_token(settings, job["subscriber_id"], next_path=f"/reports/{job_id}")
        send_report_ready_email(settings, job["email"], magic_link(settings, raw), job["site_label"])
    except Exception:
        # The report is still reachable from /reports; a mail outage must not fail the job.
        log.exception("Could not send the report-ready email for job %s", job_id)
    return "done"


def run_once(settings: Settings) -> bool:
    """Claim and process one job. True if a job was processed."""
    job = claim_next(settings)
    if job is None:
        return False
    process_job(settings, job["id"])
    return True


# ----------------------------------------------------------------------------
# Deletion and retention
# ----------------------------------------------------------------------------


def delete_job_data(settings: Settings, job_id: str) -> None:
    """Remove a job's files and site-derived fields; the row stays as status 'deleted'.

    Follow-up about the site ends with it (``followup_consent`` back to 0): there is no
    site left to talk about, and a deleted report has no control to change the choice."""
    shutil.rmtree(job_dir(settings, job_id), ignore_errors=True)
    nulls = ", ".join(f"{f} = NULL" for f in SITE_DATA_FIELDS)
    with db(settings.db_path) as conn:
        conn.execute(f"UPDATE jobs SET status = 'deleted', followup_consent = 0, {nulls} WHERE id = ?",
                     (job_id,))


def erase_subscriber(settings: Settings, subscriber_id: int) -> bool:
    """Right to erasure: files, rows (cascade) and a suppression entry for sha256(email).
    False if the subscriber no longer exists."""
    with tx(settings.db_path) as conn:
        sub = conn.execute("SELECT email FROM subscribers WHERE id = ?", (subscriber_id,)).fetchone()
        if sub is None:
            return False
        job_ids = [r["id"] for r in conn.execute("SELECT id FROM jobs WHERE subscriber_id = ?",
                                                  (subscriber_id,))]
        conn.execute("INSERT INTO suppression (email_sha256, created_at) VALUES (?, ?) "
                     "ON CONFLICT(email_sha256) DO NOTHING", (email_hash(sub["email"]), now_iso()))
        conn.execute("DELETE FROM outbox WHERE to_addr = ?", (sub["email"],))
        conn.execute("DELETE FROM subscribers WHERE id = ?", (subscriber_id,))
    for job_id in job_ids:
        shutil.rmtree(job_dir(settings, job_id), ignore_errors=True)
    return True


# Confirmed accounts that no longer serve a purpose: no report left, not on the newsletter, and
# no activity since the cutoff. Every link request and sign-in appends a consent row, so the
# newest consent row (or job, or the sign-up itself) is the last activity.
INACTIVE_SUBSCRIBERS_SQL = """
SELECT s.id FROM subscribers s
WHERE s.verified_at IS NOT NULL AND s.newsletter_status != 'subscribed'
  AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.subscriber_id = s.id AND j.status != 'deleted')
  AND MAX(s.created_at, s.verified_at,
          COALESCE((SELECT MAX(c.created_at) FROM consents c WHERE c.subscriber_id = s.id), ''),
          COALESCE((SELECT MAX(j.created_at) FROM jobs j WHERE j.subscriber_id = s.id), ''),
          COALESCE((SELECT MAX(t.created_at) FROM tokens t WHERE t.subscriber_id = s.id), ''),
          COALESCE((SELECT MAX(x.expires_at) FROM sessions x WHERE x.subscriber_id = s.id), '')) < ?
"""


def sweep(settings: Settings) -> dict[str, int]:
    """Retention sweep (PDPA s.10). Safe to run at any time; returns counts for logging/tests."""
    now = now_iso()
    counts: dict[str, int] = {}

    with db(settings.db_path) as conn:
        expired_jobs = [r["id"] for r in conn.execute(
            "SELECT id FROM jobs WHERE delete_after < ? AND status != 'deleted'", (now,))]
    for job_id in expired_jobs:
        delete_job_data(settings, job_id)
    counts["jobs_expired"] = len(expired_jobs)

    purge_cutoff = iso(utcnow() - timedelta(days=settings.unverified_purge_days))
    with db(settings.db_path) as conn:
        unverified = [r["id"] for r in conn.execute(
            "SELECT id FROM subscribers WHERE verified_at IS NULL AND created_at < ?", (purge_cutoff,))]
        for sid in unverified:
            for r in conn.execute("SELECT id FROM jobs WHERE subscriber_id = ?", (sid,)):
                shutil.rmtree(job_dir(settings, r["id"]), ignore_errors=True)
        counts["unverified_purged"] = conn.execute(
            "DELETE FROM subscribers WHERE verified_at IS NULL AND created_at < ?", (purge_cutoff,)
        ).rowcount
        counts["tokens"] = conn.execute(
            "DELETE FROM tokens WHERE expires_at < ? OR uses_left <= 0", (now,)).rowcount
        counts["sessions"] = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,)).rowcount
        counts["events"] = conn.execute(
            "DELETE FROM events WHERE created_at < ?",
            (iso(utcnow() - timedelta(days=EVENT_RETENTION_DAYS)),)).rowcount
        counts["outbox"] = conn.execute(
            "DELETE FROM outbox WHERE created_at < ?",
            (iso(utcnow() - timedelta(days=OUTBOX_RETENTION_DAYS)),)).rowcount
        inactive_cutoff = iso(utcnow() - timedelta(days=settings.inactive_purge_days))
        inactive = [r["id"] for r in conn.execute(INACTIVE_SUBSCRIBERS_SQL, (inactive_cutoff,))]
    # Erased like a self-service deletion (suppression hash kept), so they are not contacted again.
    counts["inactive_erased"] = sum(erase_subscriber(settings, sid) for sid in inactive)
    with db(settings.db_path) as conn:
        live_ids = {r["id"] for r in conn.execute("SELECT id FROM jobs WHERE status != 'deleted'")}

    # Directories with no live job row (e.g. a crash between upload and insert).
    orphans = 0
    if settings.jobs_dir.is_dir():
        for child in settings.jobs_dir.iterdir():
            if child.is_dir() and child.name not in live_ids:
                try:
                    age = time.time() - child.stat().st_mtime
                except OSError:
                    continue
                if age > ORPHAN_DIR_GRACE_SECONDS:
                    shutil.rmtree(child, ignore_errors=True)
                    orphans += 1
    counts["orphan_dirs"] = orphans
    counts["stale_requeued"] = recover_stale(settings)

    if any(counts.values()):
        log.info("Retention sweep: %s", counts)
    return counts


# ----------------------------------------------------------------------------
# Inline worker thread
# ----------------------------------------------------------------------------


class Worker:
    """Single background thread: process queued jobs, sweep every 10 minutes."""

    def __init__(self, settings: Settings, sweep_interval: float = SWEEP_INTERVAL_SECONDS):
        self.settings = settings
        self.sweep_interval = sweep_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # Any 'running' row was abandoned by a previous process (crash, Ctrl+C, container stop):
        # re-queue it now rather than after the 15-minute stale cutoff.
        recover_stale(self.settings, older_than_minutes=None)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="terrain-worker", daemon=True)
        self._thread.start()
        log.info("Job worker started")

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
            if self._thread.is_alive():
                log.warning("Job worker still busy after %.0fs; its job is abandoned if the process "
                            "exits now and will be re-queued when the app next starts", timeout)
            self._thread = None
        log.info("Job worker stopped")

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        next_sweep = 0.0
        while not self._stop.is_set():
            processed = False
            try:
                if time.monotonic() >= next_sweep:
                    next_sweep = time.monotonic() + self.sweep_interval
                    sweep(self.settings)
                processed = run_once(self.settings)
            except Exception:
                log.exception("Worker loop error")
            if not processed:
                self._stop.wait(self.settings.worker_poll_seconds)
