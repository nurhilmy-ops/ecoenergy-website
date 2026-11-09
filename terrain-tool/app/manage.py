"""Staff command line for consent requests that arrive outside the tool.

The privacy notice lets people withdraw consent "by written notice to us" (PDPA s.38) and
ask in writing that direct marketing stop (s.43). Record such a request with:

    python -m app.manage withdraw someone@example.com --followup --newsletter \
        --note "Email from the subscriber, 12 Oct 2026"

``--followup`` ends staff follow-up for every live report of that address (they drop out
of the leads CSV at once); ``--newsletter`` unsubscribes the address. Each change is
appended to the consent ledger with the note, like a withdrawal made in the tool.
Run it from the terrain-tool folder with the same .env / environment as the app. On the
Lightsail server use ``sudo terrain-tool withdraw EMAIL ...``, which runs it as the app user
with ``--env-file /etc/terrain-tool/terrain-tool.env`` (the server has no .env). It never
creates a database: if none is found where the settings point, it stops with an error.

Check that email delivery works with the production settings (the server's
``sudo terrain-tool test-email ADDRESS`` runs this as the app user):

    python -m app.manage test-email you@example.com --env-file /etc/terrain-tool/terrain-tool.env

It sends one short message through the configured backend and explains a failure (for
example Amazon SES sandbox limits or wrong access keys) in plain English.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import fields
from pathlib import Path

from .config import Settings, _load_dotenv, get_settings
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


TEST_EMAIL_SUBJECT = "Test email from the EcoEnergy terrain screening tool"


def send_test_email(settings: Settings, to: str) -> None:
    """Send one plain message through the configured backend; raises whatever the backend raises."""
    from .mailer import send_mail

    text = ("This is a test message from the EcoEnergy terrain screening tool at "
            f"{settings.base_url}.\n\nIf you can read it, email delivery works: visitors will "
            "receive their sign-in links and report notices.\n")
    send_mail(settings, to, TEST_EMAIL_SUBJECT, text)


def explain_mail_error(exc: BaseException, settings: Settings) -> str:
    """Plain-English reason for a failed send (Amazon SES / botocore errors, SMTP errors)."""
    name = type(exc).__name__
    region = settings.ses_region
    error = (getattr(exc, "response", None) or {}).get("Error", {})
    code, message = error.get("Code", ""), error.get("Message", "") or str(exc)
    if name in {"NoCredentialsError", "PartialCredentialsError"}:
        return ("No AWS access keys are set on this server, so Amazon SES cannot be used yet. "
                "Run: sudo terrain-tool set-aws-keys")
    if name in {"EndpointConnectionError", "ConnectTimeoutError", "ConnectionClosedError"}:
        return (f"Could not reach Amazon SES in {region}. Check that the server can reach the "
                f"internet and that SES_REGION ({region}) is right.")
    if code == "MessageRejected" and "not verified" in message.lower():
        return ("Amazon SES refused the message: " + message + "\n"
                "While your SES account is in the sandbox it only sends to addresses you have "
                f"verified in SES (region {region}), and only from a verified domain. Verify this "
                "address under SES > Identities (or wait for production access), and check that "
                "the domain identity shows \"Verified\".")
    if code in {"InvalidClientTokenId", "UnrecognizedClientException"}:
        return ("AWS does not recognise the access key ID. Re-enter it with: sudo terrain-tool "
                "set-aws-keys. Also check that the key is Active in IAM and that the Asia Pacific "
                "(Malaysia) region is enabled for your AWS account.")
    if code == "SignatureDoesNotMatch":
        return ("The secret access key does not match the access key ID. Re-enter both with: "
                "sudo terrain-tool set-aws-keys")
    if code in {"AccessDenied", "AccessDeniedException"}:
        return ("The IAM user is not allowed to send this email: " + message + "\nCheck the "
                "terrain-tool-ses permissions policy (deploy/aws-lightsail/README.md, Part E) and "
                "that MAIL_FROM uses the address the policy allows.")
    if code in {"AccountSuspendedException", "SendingPausedException"}:
        return ("Amazon SES has paused sending for this account: " + message + "\nOpen the SES "
                "console (Account dashboard) for the reason.")
    if code in {"LimitExceededException", "TooManyRequestsException", "Throttling"}:
        return "Amazon SES sending limit reached: " + message + "\nTry again later."
    if code:
        return f"Amazon SES error {code}: {message}"
    if name.startswith("SMTP") or isinstance(exc, OSError):
        return f"The mail server could not be used ({name}): {exc}"
    return f"{name}: {exc}"


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description=__doc__.split("\n\n")[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env-file", help="settings file to use, e.g. /etc/terrain-tool/terrain-tool.env "
                                           "(its AWS keys are used too; real environment variables win)")
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("withdraw", parents=[common],
                       help="record a written withdrawal of consent (PDPA s.38 / s.43)")
    w.add_argument("email")
    w.add_argument("--followup", action="store_true", help="stop staff follow-up for every live report")
    w.add_argument("--newsletter", action="store_true", help="unsubscribe from the newsletter")
    w.add_argument("--note", required=True,
                   help='how the request arrived, e.g. "Email from the subscriber, 12 Oct 2026"')
    t = sub.add_parser("test-email", parents=[common], help="send a test email with the current mail settings")
    t.add_argument("address")
    args = parser.parse_args(argv)
    if args.env_file and not Path(args.env_file).is_file():
        parser.error(f"settings file {args.env_file} not found")
    if args.command == "test-email":
        return run_test_email(args, settings)
    if not (args.followup or args.newsletter):
        parser.error("choose --followup, --newsletter or both")
    if not args.note.strip():
        parser.error("--note must describe the request")

    settings = settings or load_settings(args.env_file)
    if not settings.db_path.is_file():
        # Never create an empty database here: that would only hide a wrong DATA_DIR / --env-file.
        print(f"No database at {settings.db_path}: nothing changed. Check DATA_DIR, or pass the "
              "server's settings with --env-file (on the server: sudo terrain-tool withdraw ...).",
              file=sys.stderr)
        return 2
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


def load_settings(env_file: str | None) -> Settings:
    """Settings as the app sees them: from ``env_file`` if given (else .env), real environment
    variables winning."""
    if env_file is None:
        return get_settings()
    # The server runs the app with this file as its environment (systemd EnvironmentFile), so
    # its variables that are not settings (the AWS keys for boto3) must reach this process too.
    settings_keys = {f.name.upper() for f in fields(Settings)}
    for key, value in _load_dotenv(Path(env_file)).items():
        if key not in settings_keys:
            os.environ.setdefault(key, value)
    return Settings.from_env(env_file=Path(env_file))


def run_test_email(args: argparse.Namespace, settings: Settings | None = None) -> int:
    if settings is None:
        settings = load_settings(args.env_file)
    sender = settings.mail_from
    backend = {"ses": f"Amazon SES ({settings.ses_region})", "smtp": f"SMTP {settings.smtp_host}:{settings.smtp_port}",
               "outbox": "the development outbox"}.get(settings.mail_backend, settings.mail_backend)
    print(f"Sending a test email to {args.address} from {sender} via {backend} ...", flush=True)
    try:
        send_test_email(settings, args.address)
    except Exception as exc:  # noqa: BLE001 - every failure is reported in plain English
        print("FAILED: " + explain_mail_error(exc, settings), file=sys.stderr)
        return 1
    print(f"Sent. Check the inbox (and the spam folder) of {args.address}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
