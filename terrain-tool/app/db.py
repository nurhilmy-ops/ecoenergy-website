"""SQLite persistence (stdlib only). One short-lived connection per call site.

The schema is deliberately small and portable to Postgres: no SQLite-only types,
ISO-8601 UTC strings for timestamps, TEXT primary keys for anything exposed in URLs.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS subscribers (
    id                INTEGER PRIMARY KEY,
    email             TEXT NOT NULL UNIQUE,              -- normalised: stripped + lower-cased
    created_at        TEXT NOT NULL,
    verified_at       TEXT,                              -- set when a magic link is first confirmed
    newsletter_status TEXT NOT NULL DEFAULT 'none',      -- none | pending | subscribed | unsubscribed
    utm_source        TEXT,                              -- first-touch attribution
    utm_medium        TEXT,
    utm_campaign      TEXT,
    referrer          TEXT
);

-- Append-only consent ledger (PDP Regulations 2013 reg 3(1): consent must be recorded and
-- maintained; reg 3(5): the burden of proving consent is on us).
CREATE TABLE IF NOT EXISTS consents (
    id             INTEGER PRIMARY KEY,
    subscriber_id  INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    purpose        TEXT NOT NULL,      -- service | newsletter (account level) | site_followup (per job)
    action         TEXT NOT NULL,      -- granted | confirmed | withdrawn
    notice_version TEXT NOT NULL,
    wording        TEXT NOT NULL,      -- exact text the person saw/ticked
    ip             TEXT,
    user_agent     TEXT,
    created_at     TEXT NOT NULL,
    job_id         TEXT                -- set for per-report consents (site_followup); NULL otherwise
);

CREATE TABLE IF NOT EXISTS tokens (
    id             INTEGER PRIMARY KEY,
    subscriber_id  INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    token_hash     TEXT NOT NULL UNIQUE,   -- sha256 hex of the raw token; raw token never stored
    next_path      TEXT,                   -- optional relative redirect after confirmation
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    uses_left      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,       -- sha256 hex of the cookie value
    subscriber_id  INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    csrf           TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,      -- secrets.token_urlsafe(16)
    subscriber_id   INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,         -- queued | running | done | failed | deleted
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    delete_after    TEXT NOT NULL,
    input_filename  TEXT,
    input_sha256    TEXT,
    site_label      TEXT,
    scheme          TEXT,                  -- lss | cress | fpv | rooftop | other | NULL
    stage           TEXT,                  -- exploring | land_secured | bidding | other | NULL
    notes           TEXT,
    error           TEXT,                  -- user-safe failure message
    followup_consent INTEGER NOT NULL DEFAULT 0,  -- 1 while staff may email about this site (opt-in
                                                  -- on the upload page; ledger rows carry job_id)
    -- derived lead summary (cleared when the job's site data is deleted)
    total_area_ha   REAL,
    state           TEXT,
    district        TEXT,
    centroid_lat    REAL,
    centroid_lon    REAL,
    kpkt_class1_pct REAL
);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS jobs_subscriber_idx ON jobs(subscriber_id, created_at);

-- Rate limiting / audit counters.
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,     -- link_email | link_ip | job_email | job_ip | ...
    key         TEXT NOT NULL,     -- sha256 of the email / IP, never the raw value
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_idx ON events(kind, key, created_at);

-- Development mail backend: messages land here and are viewable at /dev/outbox.
CREATE TABLE IF NOT EXISTS outbox (
    id          INTEGER PRIMARY KEY,
    to_addr     TEXT NOT NULL,
    subject     TEXT NOT NULL,
    text_body   TEXT NOT NULL,
    html_body   TEXT,
    headers_json TEXT,
    created_at  TEXT NOT NULL
);

-- Erased subscribers: sha256(email) so we never re-mail someone who asked to be forgotten
-- unless they actively sign up again.
CREATE TABLE IF NOT EXISTS suppression (
    email_sha256 TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def now_iso() -> str:
    return iso(utcnow())


def iso_in(**delta) -> str:
    return iso(utcnow() + timedelta(**delta))


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)  # autocommit; use BEGIN explicitly
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def db(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def tx(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Explicit IMMEDIATE transaction (takes the write lock up front)."""
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# Columns added after the first local model. init_db adds any that an existing database
# lacks, so an owner's data/app.db keeps working after an upgrade. Add new columns to both
# SCHEMA (fresh databases) and here (existing ones); SQLite's ADD COLUMN needs a constant
# default for NOT NULL columns.
COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("jobs", "followup_consent", "INTEGER NOT NULL DEFAULT 0"),
    ("consents", "job_id", "TEXT"),
)

# Objects that depend on migrated columns, created after the columns exist.
POST_MIGRATION = """
CREATE INDEX IF NOT EXISTS consents_job_idx ON consents(job_id);
"""


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Idempotent: add missing columns inside one write transaction (safe if two processes
    start at once). Returns the "table.column" names that were added."""
    added: list[str] = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table, column, ddl in COLUMN_MIGRATIONS:
            if column not in table_columns(conn, table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                added.append(f"{table}.{column}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.executescript(POST_MIGRATION)
    return added


def init_db(db_path: Path) -> list[str]:
    """Create the schema, then bring an older database up to date. Returns added columns."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with db(db_path) as conn:
        conn.executescript(SCHEMA)
        return migrate(conn)
