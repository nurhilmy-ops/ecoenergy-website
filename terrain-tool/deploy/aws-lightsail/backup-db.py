#!/usr/bin/env python3
"""Nightly copy of the terrain tool's SQLite database (run as user "terrain" by
terrain-tool-backup.service; installed by setup.sh as /usr/local/lib/terrain-tool/backup-db.py).

Uses SQLite's online backup API, so the copy is consistent while the app keeps running.
Writes BACKUP_DIR/app-YYYYMMDD.db (a second run on the same day replaces that day's copy),
checks it, and keeps only the newest KEEP copies, so deleted personal data leaves the
backups after KEEP days.

Usage: backup-db.py [DB] [BACKUP_DIR] [KEEP]
"""
from __future__ import annotations

import datetime
import os
import sqlite3
import sys
from pathlib import Path


def backup(db: Path, out_dir: Path, keep: int, today: datetime.date | None = None) -> Path | None:
    if not db.is_file():
        print(f"No database at {db} yet: nothing to back up.")
        return None
    os.umask(0o077)
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = (today or datetime.date.today()).strftime("%Y%m%d")
    dest = out_dir / f"app-{stamp}.db"
    tmp = out_dir / f".app-{stamp}.db.partial"
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(db)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        dst.execute("PRAGMA journal_mode=DELETE")       # a single self-contained file
    finally:
        dst.close()
        src.close()
    if result != "ok":
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"Backup of {db} failed its integrity check: {result}")
    os.replace(tmp, dest)
    copies = sorted(out_dir.glob("app-[0-9]*.db"))
    for old in copies[:-keep] if keep > 0 else []:
        old.unlink()
    kept = min(len(copies), keep)
    print(f"Backed up {db} to {dest} ({dest.stat().st_size:,} bytes); {kept} daily copies kept.")
    return dest


def main(argv: list[str]) -> int:
    db = Path(argv[1]) if len(argv) > 1 else Path("/var/lib/terrain-tool/app.db")
    out_dir = Path(argv[2]) if len(argv) > 2 else Path("/var/lib/terrain-tool/backups")
    keep = int(argv[3]) if len(argv) > 3 else 14
    backup(db, out_dir, keep)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
