"""Staff command line for consent requests that arrive outside the tool.

The privacy notice lets people withdraw consent "by written notice to us" (PDPA s.38) and
ask in writing that direct marketing stop (s.43). Record such a request with:

    python -m app.manage withdraw someone@example.com --followup --newsletter \
        --note "Email from the subscriber, 12 Oct 2026"

``--followup`` ends staff follow-up for every live report of that address (they drop out
of the leads CSV at once); ``--newsletter`` unsubscribes the address. Each change is
appended to the consent ledger with the note, like a withdrawal made in the tool.
Run it from the terrain-tool folder with the same .env / environment as the app.
"""
from __future__ import annotations

import argparse
import sys

from .config import Settings, get_settings
from .db import init_db, tx

STAFF_USER_AGENT = "staff record (python -m app.manage)"


def withdraw(settings: Settings, email: str, *, followup: bool, newsletter: bool, note: str) -> dict | None:
    """Apply a written withdrawal. Returns what changed, or None if the address is unknown."""
    from .main import add_consent  # the ledger writer shared with the web routes

    wording = f"Written request recorded by staff: {note.strip()}"
    changed: dict = {"followup_jobs": [], "newsletter": False}
    with tx(settings.db_path) as conn:
        sub = conn.execute("SELECT id, newsletter_status FROM subscribers WHERE email = ?",
                           (email.strip().lower(),)).fetchone()
        if sub is None:
            return None
        if followup:
            job_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM jobs WHERE subscriber_id = ? AND status != 'deleted' AND followup_consent = 1",
                (sub["id"],))]
            for job_id in job_ids:
                conn.execute("UPDATE jobs SET followup_consent = 0 WHERE id = ?", (job_id,))
                add_consent(conn, sub["id"], "site_followup", "withdrawn", wording, settings.notice_version,
                            None, STAFF_USER_AGENT, job_id=job_id)
            changed["followup_jobs"] = job_ids
        if newsletter and sub["newsletter_status"] != "unsubscribed":
            add_consent(conn, sub["id"], "newsletter", "withdrawn", wording, settings.notice_version,
                        None, STAFF_USER_AGENT)
            conn.execute("UPDATE subscribers SET newsletter_status = 'unsubscribed' WHERE id = ?", (sub["id"],))
            changed["newsletter"] = True
    return changed


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("withdraw", help="record a written withdrawal of consent (PDPA s.38 / s.43)")
    w.add_argument("email")
    w.add_argument("--followup", action="store_true", help="stop staff follow-up for every live report")
    w.add_argument("--newsletter", action="store_true", help="unsubscribe from the newsletter")
    w.add_argument("--note", required=True,
                   help='how the request arrived, e.g. "Email from the subscriber, 12 Oct 2026"')
    args = parser.parse_args(argv)
    if not (args.followup or args.newsletter):
        parser.error("choose --followup, --newsletter or both")
    if not args.note.strip():
        parser.error("--note must describe the request")

    settings = settings or get_settings()
    init_db(settings.db_path)
    changed = withdraw(settings, args.email, followup=args.followup, newsletter=args.newsletter,
                       note=args.note)
    if changed is None:
        print(f"No account for {args.email.strip().lower()}; nothing changed.", file=sys.stderr)
        return 1
    if args.followup:
        print(f"Staff follow-up withdrawn for {len(changed['followup_jobs'])} report(s).")
    if args.newsletter:
        print("Newsletter: unsubscribed." if changed["newsletter"] else "Newsletter: already unsubscribed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
