"""Job queue, processing, worker thread and retention sweeps."""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import timedelta

from app import jobs
from app.db import db, init_db, iso, now_iso, utcnow


def ago(**delta) -> str:
    return iso(utcnow() - timedelta(**delta))


def add_subscriber(settings, email="s@example.com", verified=True, created_at=None) -> int:
    init_db(settings.db_path)
    with db(settings.db_path) as conn:
        cur = conn.execute("INSERT INTO subscribers (email, created_at, verified_at) VALUES (?, ?, ?)",
                           (email, created_at or now_iso(), now_iso() if verified else None))
        return cur.lastrowid


def add_job(settings, subscriber_id, job_id, status="queued", created_at=None, kml=b"<kml/>", **cols) -> str:
    d = jobs.job_dir(settings, job_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "input.kml").write_bytes(kml)
    jobs.enqueue_job(settings, job_id, subscriber_id, input_filename="site.kml", input_sha256="0" * 64,
                     site_label=cols.pop("site_label", "Label"), scheme="lss")
    sets = {"status": status, **cols}
    if created_at:
        sets["created_at"] = created_at
    with db(settings.db_path) as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), job_id))
    return job_id


def test_claim_next_is_fifo_and_exclusive(settings, query):
    sid = add_subscriber(settings)
    add_job(settings, sid, "job-newer-0001", created_at=ago(minutes=1))
    add_job(settings, sid, "job-older-0001", created_at=ago(minutes=5))
    add_job(settings, sid, "job-done-00001", status="done", created_at=ago(minutes=9))

    first = jobs.claim_next(settings)
    assert first["id"] == "job-older-0001" and first["status"] == "running" and first["started_at"]
    assert jobs.claim_next(settings)["id"] == "job-newer-0001"
    assert jobs.claim_next(settings) is None


def test_concurrent_claims_never_double_claim(settings):
    sid = add_subscriber(settings)
    for i in range(12):
        add_job(settings, sid, f"job-concurrent-{i:02d}", created_at=ago(seconds=100 - i))
    claimed: list[str] = []
    lock = threading.Lock()

    def worker():
        while (job := jobs.claim_next(settings)) is not None:
            with lock:
                claimed.append(job["id"])

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == sorted(f"job-concurrent-{i:02d}" for i in range(12))


def test_process_job_success_stores_lead_fields_and_mails(settings, fake_engine, query):
    sid = add_subscriber(settings, "lead@example.com")
    add_job(settings, sid, "job-success-001", status="running", site_label="Parcel A")
    assert jobs.process_job(settings, "job-success-001") == "done"
    job = query("SELECT * FROM jobs")[0]
    assert job["status"] == "done" and job["finished_at"] and job["error"] is None
    assert (job["total_area_ha"], job["state"], job["district"]) == (123.4, "Selangor", "Kuala Langat")
    assert (job["centroid_lat"], job["centroid_lon"], job["kpkt_class1_pct"]) == (2.905, 101.505, 96.5)
    meta = fake_engine.run_calls[0]
    assert set(meta) == {"report_id", "generated_at", "site_label", "scheme", "stage", "input_filename"}
    assert meta["report_id"] == "job-success-001" and meta["scheme"] == "lss"
    out = jobs.job_dir(settings, "job-success-001")
    assert (out / "report.pdf").exists() and (out / "result.json").exists()
    mail = query("SELECT * FROM outbox")[0]
    assert mail["to_addr"] == "lead@example.com" and "Parcel A" in mail["text_body"]
    assert "/start?t=" in mail["text_body"]
    token = query("SELECT * FROM tokens")[0]
    assert token["next_path"] == "/reports/job-success-001" and token["uses_left"] == settings.token_max_uses


def test_process_job_screening_error_and_crash(settings, fake_engine, query):
    sid = add_subscriber(settings)
    add_job(settings, sid, "job-scr-error-1", status="running")
    fake_engine.run_behaviour = "screening_error"
    assert jobs.process_job(settings, "job-scr-error-1") == "failed"
    assert "could not be reached" in query("SELECT error FROM jobs WHERE id='job-scr-error-1'")[0]["error"]

    add_job(settings, sid, "job-crash-00001", status="running")
    fake_engine.run_behaviour = "crash"
    assert jobs.process_job(settings, "job-crash-00001") == "failed"
    assert query("SELECT error FROM jobs WHERE id='job-crash-00001'")[0]["error"] == jobs.GENERIC_FAILURE
    assert query("SELECT * FROM outbox") == []            # no "ready" mail for failures


def test_process_job_when_engine_missing(settings, monkeypatch, query):
    monkeypatch.setitem(sys.modules, "app.terrain", None)        # import raises ImportError
    sid = add_subscriber(settings)
    add_job(settings, sid, "job-no-engine-1", status="running")
    assert jobs.process_job(settings, "job-no-engine-1") == "failed"
    assert query("SELECT error FROM jobs")[0]["error"] == jobs.GENERIC_FAILURE


def test_job_deleted_while_running_leaves_no_files(settings, fake_engine, query):
    sid = add_subscriber(settings)
    add_job(settings, sid, "job-del-running", status="running")
    original = sys.modules["app.terrain"].run_screening

    def run_then_user_deletes(path, out_dir, s, meta):
        result = original(path, out_dir, s, meta)
        with db(settings.db_path) as conn:      # user pressed Delete mid-run
            conn.execute("UPDATE jobs SET status = 'deleted' WHERE id = ?", (meta["report_id"],))
        return result

    sys.modules["app.terrain"].run_screening = run_then_user_deletes
    assert jobs.process_job(settings, "job-del-running") == "deleted"
    assert not jobs.job_dir(settings, "job-del-running").exists()
    assert query("SELECT status FROM jobs")[0]["status"] == "deleted"
    assert query("SELECT * FROM outbox") == []


def test_recover_stale_requeues_old_running_jobs(settings, query):
    sid = add_subscriber(settings)
    add_job(settings, sid, "job-stale-00001", status="running", started_at=ago(minutes=20))
    add_job(settings, sid, "job-fresh-00001", status="running", started_at=ago(minutes=2))
    assert jobs.recover_stale(settings) == 1
    status = {r["id"]: r["status"] for r in query("SELECT id, status FROM jobs")}
    assert status == {"job-stale-00001": "queued", "job-fresh-00001": "running"}


def test_sweep_applies_retention(settings, query):
    verified = add_subscriber(settings, "kept@example.com")
    stale_unverified = add_subscriber(settings, "stale@example.com", verified=False, created_at=ago(days=8))
    add_subscriber(settings, "recent@example.com", verified=False, created_at=ago(days=1))

    add_job(settings, verified, "job-expired-001", status="done", delete_after=ago(minutes=1),
            total_area_ha=10.0, state="Johor", notes="secret", followup_consent=1)
    add_job(settings, verified, "job-current-001", status="done")
    with db(settings.db_path) as conn:
        conn.execute("INSERT INTO tokens (subscriber_id, token_hash, created_at, expires_at, uses_left) "
                     "VALUES (?, 'expired', ?, ?, 3), (?, 'used-up', ?, ?, 0), (?, 'live', ?, ?, 3)",
                     (verified, ago(days=4), ago(days=1), verified, now_iso(), iso(utcnow() + timedelta(hours=1)),
                      verified, now_iso(), iso(utcnow() + timedelta(hours=1))))
        conn.execute("INSERT INTO sessions (id, subscriber_id, csrf, created_at, expires_at) VALUES "
                     "('old', ?, 'c', ?, ?), ('live', ?, 'c', ?, ?)",
                     (verified, ago(days=2), ago(days=1), verified, now_iso(), iso(utcnow() + timedelta(hours=1))))
        conn.execute("INSERT INTO events (kind, key, created_at) VALUES ('link_ip', 'k', ?), ('link_ip', 'k', ?)",
                     (ago(days=3), now_iso()))
        conn.execute("INSERT INTO outbox (to_addr, subject, text_body, created_at) VALUES "
                     "('a@example.com', 'old', 'x', ?), ('a@example.com', 'new', 'x', ?)", (ago(days=8), now_iso()))
        conn.execute("INSERT INTO consents (subscriber_id, purpose, action, notice_version, wording, created_at) "
                     "VALUES (?, 'service', 'granted', 'v', 'w', ?)", (stale_unverified, ago(days=8)))

    orphan_old = settings.jobs_dir / "orphan-old-dir"
    orphan_new = settings.jobs_dir / "orphan-new-dir"
    for d in (orphan_old, orphan_new):
        d.mkdir()
        (d / "input.kml").write_bytes(b"<kml/>")
    old = time.time() - 2 * 3600
    os.utime(orphan_old, (old, old))

    counts = jobs.sweep(settings)

    expired = query("SELECT * FROM jobs WHERE id = 'job-expired-001'")[0]
    assert expired["status"] == "deleted"
    assert expired["total_area_ha"] is None and expired["state"] is None and expired["notes"] is None
    assert expired["site_label"] is None and expired["input_filename"] is None
    assert expired["followup_consent"] == 0               # follow-up ends with the site data
    assert not jobs.job_dir(settings, "job-expired-001").exists()
    assert jobs.job_dir(settings, "job-current-001").exists()
    assert query("SELECT status FROM jobs WHERE id = 'job-current-001'")[0]["status"] == "done"

    emails = {r["email"] for r in query("SELECT email FROM subscribers")}
    assert emails == {"kept@example.com", "recent@example.com"}
    assert query("SELECT * FROM consents WHERE subscriber_id = ?", (stale_unverified,)) == []
    assert {r["token_hash"] for r in query("SELECT token_hash FROM tokens")} == {"live"}
    assert {r["id"] for r in query("SELECT id FROM sessions")} == {"live"}
    assert len(query("SELECT * FROM events")) == 1
    assert [r["subject"] for r in query("SELECT subject FROM outbox")] == ["new"]
    assert not orphan_old.exists() and orphan_new.exists()
    assert counts["jobs_expired"] == 1 and counts["unverified_purged"] == 1 and counts["orphan_dirs"] == 1


def test_worker_thread_processes_jobs_and_stops(settings, fake_engine, query):
    sid = add_subscriber(settings)
    add_job(settings, sid, "job-worker-0001")
    worker = jobs.Worker(settings)
    worker.start()
    try:
        deadline = time.time() + 10
        while time.time() < deadline and query("SELECT status FROM jobs")[0]["status"] != "done":
            time.sleep(0.05)
    finally:
        worker.stop(timeout=5)
    assert query("SELECT status FROM jobs")[0]["status"] == "done"
    assert not worker.running


def test_inline_worker_runs_with_app_lifespan(app_factory):
    flow = app_factory("inline", worker_inline=True)
    with flow.client:                                      # runs lifespan → starts the worker
        assert flow.client.app.state.worker.running
        flow.login("inline@example.com")
        job_id = flow.upload_job()
        deadline = time.time() + 10
        status = None
        while time.time() < deadline:
            status = flow.client.get(f"/api/reports/{job_id}/status").json()["status"]
            if status == "done":
                break
            time.sleep(0.05)
        assert status == "done"
        worker = flow.client.app.state.worker
    assert not worker.running                              # stopped on shutdown


# ----------------------------------------------------------------------------
# Follow-up consent column and the in-place migration of older databases
# ----------------------------------------------------------------------------


def test_enqueue_job_records_followup_choice(settings, query):
    sid = add_subscriber(settings)
    for job_id, choice in (("job-fu-yes-01", True), ("job-fu-no-001", False)):
        jobs.job_dir(settings, job_id).mkdir(parents=True)
        jobs.enqueue_job(settings, job_id, sid, input_filename="a.kml", input_sha256="0" * 64,
                         followup_consent=choice)
    jobs.enqueue_job(settings, "job-fu-dflt01", sid, input_filename="a.kml", input_sha256="0" * 64)
    states = {r["id"]: r["followup_consent"] for r in query("SELECT id, followup_consent FROM jobs")}
    assert states == {"job-fu-yes-01": 1, "job-fu-no-001": 0, "job-fu-dflt01": 0}
    jobs.delete_job_data(settings, "job-fu-yes-01")
    assert query("SELECT followup_consent FROM jobs WHERE id = 'job-fu-yes-01'")[0]["followup_consent"] == 0


# The first local model's tables, before followup_consent / consents.job_id existed.
LEGACY_SCHEMA = """
CREATE TABLE subscribers (
    id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, verified_at TEXT,
    newsletter_status TEXT NOT NULL DEFAULT 'none', utm_source TEXT, utm_medium TEXT, utm_campaign TEXT,
    referrer TEXT
);
CREATE TABLE consents (
    id INTEGER PRIMARY KEY,
    subscriber_id INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL, action TEXT NOT NULL, notice_version TEXT NOT NULL, wording TEXT NOT NULL,
    ip TEXT, user_agent TEXT, created_at TEXT NOT NULL
);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY, subscriber_id INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
    delete_after TEXT NOT NULL, input_filename TEXT, input_sha256 TEXT, site_label TEXT, scheme TEXT,
    stage TEXT, notes TEXT, error TEXT, total_area_ha REAL, state TEXT, district TEXT, centroid_lat REAL,
    centroid_lon REAL, kpkt_class1_pct REAL
);
"""


def make_legacy_db(path) -> None:
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute("INSERT INTO subscribers (id, email, created_at, verified_at) "
                 "VALUES (1, 'old@example.com', '2026-10-01T00:00:00+00:00', '2026-10-01T00:05:00+00:00')")
    for purpose in ("service", "site_followup"):              # the old bundled grant
        conn.execute("INSERT INTO consents (subscriber_id, purpose, action, notice_version, wording, created_at) "
                     "VALUES (1, ?, 'granted', '2026-10-draft-1', 'old wording', '2026-10-01T00:00:00+00:00')",
                     (purpose,))
    conn.execute("INSERT INTO jobs (id, subscriber_id, status, created_at, delete_after, site_label) "
                 "VALUES ('legacy-job-0001', 1, 'done', '2026-10-01T00:10:00+00:00', '2099-01-01T00:00:00+00:00', "
                 "'Old site')")
    conn.commit()
    conn.close()


def test_init_db_migrates_an_existing_database_in_place(tmp_path):
    from app.db import table_columns

    path = tmp_path / "data" / "app.db"
    make_legacy_db(path)
    added = init_db(path)
    assert sorted(added) == ["consents.job_id", "jobs.followup_consent"]
    with db(path) as conn:
        assert "followup_consent" in table_columns(conn, "jobs")
        assert "job_id" in table_columns(conn, "consents")
        job = dict(conn.execute("SELECT * FROM jobs").fetchone())
        # Existing data survives; old screenings default to no follow-up (the bundled grant
        # is history, not consent for a specific site).
        assert job["site_label"] == "Old site" and job["followup_consent"] == 0
        assert [r["job_id"] for r in conn.execute("SELECT job_id FROM consents")] == [None, None]
        indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "consents_job_idx" in indexes
    # Idempotent: a second start changes nothing.
    assert init_db(path) == []
    # A fresh database needs no migration.
    assert init_db(tmp_path / "fresh" / "app.db") == []


def test_app_runs_on_a_migrated_database(tmp_path, app_factory):
    make_legacy_db(tmp_path / "legacy" / "data" / "app.db")
    flow = app_factory("legacy")
    flow.login("old@example.com")
    job_id = flow.upload_job(followup="yes")
    with db(flow.settings.db_path) as conn:
        states = {r["id"]: r["followup_consent"] for r in conn.execute("SELECT id, followup_consent FROM jobs")}
        assert states == {"legacy-job-0001": 0, job_id: 1}
        ledger = [dict(r) for r in conn.execute(
            "SELECT purpose, action, job_id FROM consents WHERE purpose = 'site_followup' ORDER BY id")]
    # The legacy account-level grant is neither confirmed nor copied on the next login.
    assert ledger == [{"purpose": "site_followup", "action": "granted", "job_id": None},
                      {"purpose": "site_followup", "action": "granted", "job_id": job_id}]
    page = flow.client.get("/account")
    assert page.status_code == 200 and "Old site" in page.text
