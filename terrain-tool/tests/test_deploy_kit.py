"""The Amazon Lightsail server kit in deploy/aws-lightsail/: scripts, systemd units, Caddyfile,
settings template and the owner's guide. The full install is exercised on a real Ubuntu 24.04
(systemd) machine; these checks keep the files consistent without touching this computer."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "deploy" / "aws-lightsail"
SETUP = KIT / "setup.sh"
HELPER = KIT / "terrain-tool"
PR_BRANCH = "claude/admiring-albattani-j1beqs"
RAW = "https://raw.githubusercontent.com/nurhilmy-ops/ecoenergy-website"
PROCESS_KEYS = {"HOST", "PORT", "LOG_LEVEL"}           # read by python -m app, not Settings fields

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def unit(path: Path) -> dict[str, list[str]]:
    """systemd unit file as {key: [values]} (sections flattened; comments dropped)."""
    out: dict[str, list[str]] = {}
    for line in text(path).splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";", "[")):
            continue
        key, _, value = line.partition("=")
        out.setdefault(key.strip(), []).append(value.strip())
    return out


def env_lines(body: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in body.splitlines() if re.match(r"^[A-Z][A-Z0-9_]*=", line))


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run that leaves the exit code to the test."""
    kwargs.setdefault("timeout", 60)
    return subprocess.run(args, check=False, **kwargs)


def fake_os_release(tmp_path: Path, distro: str, version: str, pretty: str) -> Path:
    path = tmp_path / "os-release"
    path.write_text(f'ID={distro}\nVERSION_ID="{version}"\nPRETTY_NAME="{pretty}"\n', encoding="utf-8")
    return path


def as_unprivileged_user() -> list[str]:
    """Command prefix that runs as an ordinary user (this test suite may run as root)."""
    if os.geteuid() != 0:
        return []
    setpriv = shutil.which("setpriv")
    if setpriv is None:
        pytest.skip("running as root and setpriv is not available to drop privileges")
    prefix = [setpriv, "--reuid=65534", "--regid=65534", "--clear-groups"]
    uid = subprocess.run([*prefix, "id", "-u"], capture_output=True, text=True, check=True).stdout.strip()
    assert uid != "0"                       # never run setup.sh as root from the test suite
    return prefix


# ----------------------------------------------------------------------------
# Scripts
# ----------------------------------------------------------------------------


@needs_bash
@pytest.mark.parametrize("script", [SETUP, HELPER], ids=["setup.sh", "terrain-tool"])
def test_scripts_parse_and_are_executable(script):
    subprocess.run(["bash", "-n", str(script)], check=True)
    assert os.access(script, os.X_OK), f"{script.name} must be executable (git keeps the bit)"
    assert text(script).startswith("#!/usr/bin/env bash\n")
    assert "set -Eeuo pipefail" in text(script)
    # Whole body in main(), called on the last line: safe when piped from curl (a command that
    # reads stdin cannot swallow the rest) and when an update replaces the file mid-run.
    last = [line for line in text(script).splitlines() if line.strip()][-1]
    assert last == 'main "$@"; exit $?'


def shellcheck_binary() -> str | None:
    found = shutil.which("shellcheck")
    if found:
        return found
    beside_python = Path(sys.executable).parent / "shellcheck"   # pip install shellcheck-py
    return str(beside_python) if beside_python.exists() else None


def test_shellcheck_is_clean():
    binary = shellcheck_binary()
    if binary is None:
        pytest.skip("shellcheck not installed (pip install shellcheck-py)")
    result = run([binary, "-x", str(SETUP), str(HELPER)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@needs_bash
def test_setup_refuses_other_systems(tmp_path):
    """The OS is checked before anything else, for any user."""
    debian = fake_os_release(tmp_path, "debian", "12", "Debian GNU/Linux 12 (bookworm)")
    result = run(["bash"], input=SETUP.read_bytes(), capture_output=True,
                            env={**os.environ, "TT_OS_RELEASE": str(debian)}, timeout=30)
    err = result.stderr.decode()
    assert result.returncode == 1
    assert "SETUP STOPPED" in err and "Ubuntu 24.04 LTS" in err and "Debian GNU/Linux 12" in err

    old = fake_os_release(tmp_path, "ubuntu", "20.04", "Ubuntu 20.04.6 LTS")
    result = run(["bash", str(SETUP)], capture_output=True, text=True,
                            env={**os.environ, "TT_OS_RELEASE": str(old)}, timeout=30)
    assert result.returncode == 1 and "Ubuntu 20.04.6 LTS" in result.stderr
    # 22.04 too: its python3.11 is a pre-release build from universe without regular security fixes.
    jammy = fake_os_release(tmp_path, "ubuntu", "22.04", "Ubuntu 22.04.5 LTS")
    result = run(["bash", str(SETUP)], capture_output=True, text=True,
                            env={**os.environ, "TT_OS_RELEASE": str(jammy)}, timeout=30)
    assert result.returncode == 1 and "Ubuntu 22.04.5 LTS" in result.stderr
    assert "PYTHON_PACKAGES=(python3 python3-venv)" in text(SETUP) and "python3.11-venv" not in text(SETUP)


@needs_bash
def test_setup_refuses_to_run_without_root():
    prefix = as_unprivileged_user()
    with tempfile.TemporaryDirectory() as folder:       # readable by the unprivileged user
        os.chmod(folder, 0o755)
        ubuntu = fake_os_release(Path(folder), "ubuntu", "24.04", "Ubuntu 24.04.3 LTS")
        os.chmod(ubuntu, 0o644)
        # As piped from curl, the way the owner runs it (but without sudo).
        result = run([*prefix, "bash"], input=SETUP.read_bytes(), capture_output=True,
                                timeout=30, cwd="/",
                                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TT_OS_RELEASE": str(ubuntu)})
    err = result.stderr.decode()
    assert result.returncode == 1, err
    assert "administrator rights" in err and "sudo bash" in err


@needs_bash
def test_helper_needs_root_except_for_help():
    prefix = as_unprivileged_user()
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    result = run([*prefix, "bash", str(HELPER), "status"], capture_output=True, text=True,
                            env=env, cwd="/", timeout=30)
    assert result.returncode == 1 and "sudo terrain-tool status" in result.stderr
    result = run([*prefix, "bash", str(HELPER), "help"], capture_output=True, text=True,
                            env=env, cwd="/", timeout=30)
    assert result.returncode == 0
    for command in ("status", "logs [-f]", "restart", "update [--ref NAME]", "admin-password",
                    "set-aws-keys", "set-turnstile-keys", "test-email ADDRESS",
                    "withdraw EMAIL [--followup] [--newsletter] --note TEXT", "backup-now", "help"):
        assert f"sudo terrain-tool {command}" in result.stdout, command
    result = run([*prefix, "bash", str(HELPER), "frobnicate"], capture_output=True, text=True,
                            env=env, cwd="/", timeout=30)
    assert result.returncode == 1 and "Unknown command" in result.stderr


def test_setup_paths_match_the_unit_and_the_helper():
    setup, helper = text(SETUP), text(HELPER)
    for line in ("readonly BASE=/opt/terrain-tool", "readonly SRC=$BASE/src", "readonly VENV=$BASE/venv",
                 "readonly APP_DIR=$SRC/terrain-tool", "readonly DATA_DIR=/var/lib/terrain-tool",
                 "readonly ETC_DIR=/etc/terrain-tool", "readonly ENV_FILE=$ETC_DIR/terrain-tool.env",
                 "readonly APP_USER=terrain", "readonly HEALTH_URL=http://127.0.0.1:8000/healthz"):
        assert line in setup, line
    for line in ("readonly ENV_FILE=/etc/terrain-tool/terrain-tool.env", "readonly SRC=/opt/terrain-tool/src",
                 "readonly VENV=/opt/terrain-tool/venv", "readonly BACKUP_DIR=/var/lib/terrain-tool/backups",
                 "readonly HEALTH_URL=http://127.0.0.1:8000/healthz"):
        assert line in helper, line
    # Each kit file setup.sh installs exists.
    for name in re.findall(r'"\$KIT_DIR/([^"]+)"', setup):
        assert (KIT / name).is_file(), name


def test_setup_sources_and_secrets():
    setup = text(SETUP)
    assert "readonly DEFAULT_REPO=https://github.com/nurhilmy-ops/ecoenergy-website.git" in setup
    assert "readonly DEFAULT_DOMAIN=tools.ecoconsultancy.services" in setup
    assert "TOOL_REF=${TOOL_REF:-main}" in setup                   # default ref when none is recorded
    # Shallow, sparse checkout of terrain-tool/ only; reruns fetch and hard-reset to the ref.
    assert "git clone --quiet --depth 1 --filter=blob:none --sparse --branch \"$TOOL_REF\"" in setup
    assert "sparse-checkout set terrain-tool" in setup
    assert "checkout --quiet --force --detach FETCH_HEAD" in setup
    assert 'printf \'%s\\n\' "$TOOL_REF" >"$REF_FILE"' in setup
    # Caddy from its official apt repository (https://caddyserver.com/docs/install).
    assert "https://dl.cloudsmith.io/public/caddy/stable/gpg.key" in setup
    assert "https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt" in setup
    assert "/usr/share/keyrings/caddy-stable-archive-keyring.gpg" in setup
    assert "debian-keyring" in setup and "debian-archive-keyring" in setup and "apt-transport-https" in setup
    # pip installs the pinned versions (and moves an existing environment to them), plus boto3.
    assert ('--prefer-binary --upgrade \\\n    -c "$KIT_DIR/constraints.txt" -r "$APP_DIR/requirements.txt" boto3'
            in setup)
    # Secrets are generated on the server (never fixed), long enough, and created only once.
    assert "random_token 64" in setup and "random_token 24" in setup
    assert "secrets.choice" in setup
    assert 'if [[ ! -f $ENV_FILE ]]; then' in setup
    assert 'if ! grep -q "^$key=" "$ENV_FILE"; then' in setup   # reruns only add missing keys
    # Swap: 2 GB once, one fstab line, low swappiness.
    assert "readonly SWAP_MB=2048" in setup and "vm.swappiness = 10" in setup
    assert "! grep -qE \"^[[:space:]]*${SWAPFILE}[[:space:]]\" /etc/fstab" in setup
    # Non-interactive: no prompts from apt, needrestart or git.
    for setting in ("DEBIAN_FRONTEND=noninteractive", "NEEDRESTART_MODE=a", "GIT_TERMINAL_PROMPT=0",
                    "DPkg::Lock::Timeout=600"):
        assert setting in setup, setting
    # The admin password never goes to the screen output, which is also the setup log.
    assert "env_value ADMIN_PASSWORD" not in setup and "sudo terrain-tool admin-password" in setup


def test_setup_survives_locks_and_a_closed_window():
    setup = text(SETUP)
    # `apt-get update` does not wait for the package-list lock: wait for Ubuntu's own jobs, then retry.
    assert "systemctl is-active --quiet apt-daily.service apt-daily-upgrade.service" in setup
    assert "[[ $1 == update ]] && tail -n \"+$((start + 1))\" \"$LOG\" | grep -q 'Could not get lock'" in setup
    # An install cut off earlier is finished first (else every apt-get install refuses to run).
    assert "dpkg --force-confdef --force-confold --configure -a" in setup
    assert setup.index("dpkg --force-confdef") < setup.index("  apt_get update\n")
    # A lost terminal (SIGHUP) does not stop it; output also goes to the log through tee.
    assert "trap '' HUP" in setup
    assert "exec > >(tee -a \"$LOG\" --output-error=warn) 2>&1" in setup
    assert setup.index("trap '' HUP") < setup.index("exec > >(tee")


def test_setup_stops_the_tool_while_updating_and_puts_back_the_previous_version():
    setup = text(SETUP)
    fetch = setup[setup.index("fetch_source() {"):setup.index("\n}\n", setup.index("fetch_source() {"))]
    # Before switching the code: remember the running commit and stop the service.
    assert fetch.index('update-ref "$PREV_GIT_REF" "$current"') < fetch.index("checkout --quiet --force --detach FETCH_HEAD")
    assert fetch.index("systemctl stop terrain-tool.service") < fetch.index("checkout --quiet --force --detach FETCH_HEAD")
    assert 'if [[ -n $current && $current != "$new" ]]; then' in fetch     # only when the code changes
    # Every failure path restores it; success forgets it.
    die = setup[setup.index("die() {"):setup.index("}", setup.index("die() {"))]
    on_error = setup[setup.index("on_error() {"):setup.index("\n}\n", setup.index("on_error() {"))]
    assert "restore_previous" in die and "restore_previous" in on_error
    restore = setup[setup.index("restore_previous() {"):setup.index("\n}\n", setup.index("restore_previous() {"))]
    for step in ('checkout --quiet --force --detach "$commit"', '-c "$KIT_DIR/constraints.txt"',
                 "install -m 0644 \"$KIT_DIR/terrain-tool.service\"", "systemctl restart terrain-tool.service",
                 "health_ok 90"):
        assert step in restore, step
    assert "((CAN_RESTORE)) && [[ -f $PREV_FILE ]] || return 0" in restore   # not before the lock is held
    assert setup.index("start_app\n  forget_previous\n") > setup.index("install_caddy\n")
    assert "The previous settings are unchanged" not in setup


def test_constraints_pin_every_requirement_to_a_matching_version():
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    pins = {}
    for line in text(KIT / "constraints.txt").splitlines():
        if line.strip() and not line.startswith("#"):
            name, _, version = line.partition("==")
            assert version and "<" not in version and ">" not in version, line
            pins[canonicalize_name(name)] = version.strip()
    wanted = [Requirement(line.split("#")[0].strip()) for line in text(ROOT / "requirements.txt").splitlines()
              if line.split("#")[0].strip()] + [Requirement("boto3")]
    for req in wanted:
        name = canonicalize_name(req.name)
        assert name in pins, f"{req.name} is not pinned in constraints.txt"
        assert req.specifier.contains(pins[name], prereleases=True), (req, pins[name])
    # The packages the app imports at start-up come with their own pins (not left to chance).
    for dep in ("starlette", "h11", "botocore", "pydantic", "pillow", "urllib3", "certifi"):
        assert dep in pins, dep


# ----------------------------------------------------------------------------
# systemd units
# ----------------------------------------------------------------------------


def test_app_unit_runs_as_terrain_with_hardening():
    u = unit(KIT / "terrain-tool.service")
    expected = {
        "User": "terrain", "Group": "terrain",
        "EnvironmentFile": "/etc/terrain-tool/terrain-tool.env",
        "WorkingDirectory": "/opt/terrain-tool/src/terrain-tool",
        "ExecStart": "/opt/terrain-tool/venv/bin/python -m app",
        "Restart": "always", "RestartSec": "5",
        "NoNewPrivileges": "true", "PrivateTmp": "true", "ProtectSystem": "strict",
        "ReadWritePaths": "/var/lib/terrain-tool", "ProtectHome": "true",
        "ProtectKernelTunables": "true", "ProtectKernelModules": "true",
        "ProtectControlGroups": "true", "RestrictSUIDSGID": "true", "LockPersonality": "true",
        "MemoryMax": "1500M", "WantedBy": "multi-user.target",
    }
    for key, value in expected.items():
        assert u.get(key) == [value], (key, u.get(key))
    # Longer than the worker's 30 s wait for a running screening.
    assert int(u["TimeoutStopSec"][0]) > 30
    assert u["CapabilityBoundingSet"] == [""]


def test_backup_units():
    service, timer = unit(KIT / "terrain-tool-backup.service"), unit(KIT / "terrain-tool-backup.timer")
    assert service["User"] == ["terrain"] and service["Type"] == ["oneshot"]
    assert service["ExecStart"] == [("/usr/bin/python3 /usr/local/lib/terrain-tool/backup-db.py "
                                     "/var/lib/terrain-tool/app.db /var/lib/terrain-tool/backups 14")]
    assert service["ReadWritePaths"] == ["/var/lib/terrain-tool"] and service["ProtectSystem"] == ["strict"]
    assert timer["OnCalendar"] == ["*-*-* 02:30:00 Asia/Kuala_Lumpur"] and timer["Persistent"] == ["true"]
    journald = unit(KIT / "journald-terrain-tool.conf")
    assert journald["SystemMaxUse"] == ["500M"] and journald["MaxRetentionSec"] == ["30day"]
    # Daily journal files, so whole files older than 30 days can go; nothing copied to /var/log/syslog.
    assert journald["MaxFileSec"] == ["1day"] and journald["ForwardToSyslog"] == ["no"]


def test_unattended_upgrades_cover_caddy_and_reboot_after_the_snapshot():
    conf = text(KIT / "unattended-upgrades.conf")
    assert 'Unattended-Upgrade::Origins-Pattern:: "origin=cloudsmith/caddy/stable";' in conf
    assert 'Unattended-Upgrade::Automatic-Reboot "true";' in conf
    # Snapshot at 19:00 UTC can take until 19:45 (Lightsail): reboot at 20:00 UTC = 04:00 Malaysia.
    assert 'Unattended-Upgrade::Automatic-Reboot-Time "20:00";' in conf
    timer = unit(KIT / "terrain-tool-backup.timer")
    assert timer["OnCalendar"] == ["*-*-* 02:30:00 Asia/Kuala_Lumpur"]
    for path in (SETUP, HELPER, KIT / "README.md"):
        assert "03:30" not in text(path), path
        assert "04:00 Malaysia time" in text(path) or "**04:00 Malaysia" in text(path), path


def load_backup_module(monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)     # no __pycache__ inside the kit
    spec = importlib.util.spec_from_file_location("backup_db", KIT / "backup-db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_script_copies_a_live_wal_database_and_keeps_14(tmp_path, monkeypatch):
    backup_db = load_backup_module(monkeypatch)
    db = tmp_path / "app.db"
    live = sqlite3.connect(db)
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("CREATE TABLE subscribers (email TEXT)")
    live.execute("INSERT INTO subscribers VALUES ('a@example.com')")
    live.commit()                                   # still open: the copy must see committed rows
    out = tmp_path / "backups"
    today = date(2026, 11, 30)
    for days in range(1, 20):                       # older copies from previous nights
        out.mkdir(exist_ok=True)
        (out / f"app-{(today - timedelta(days=days)):%Y%m%d}.db").write_bytes(b"old")
    dest = backup_db.backup(db, out, 14, today=today)
    live.close()
    assert dest == out / "app-20261130.db"
    copy = sqlite3.connect(dest)
    assert copy.execute("SELECT email FROM subscribers").fetchall() == [("a@example.com",)]
    assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"   # one self-contained file
    copy.close()
    kept = sorted(p.name for p in out.glob("app-*.db"))
    assert len(kept) == 14 and kept[-1] == "app-20261130.db" and kept[0] == "app-20261117.db"
    assert oct(dest.stat().st_mode & 0o777) == "0o600"
    assert not list(out.glob(".*partial"))
    # No database yet (fresh install): nothing to do, no error.
    assert backup_db.backup(tmp_path / "missing.db", out, 14) is None


# ----------------------------------------------------------------------------
# Caddy
# ----------------------------------------------------------------------------


def test_caddyfile_template():
    caddy = text(KIT / "Caddyfile")
    body = "\n".join(line for line in caddy.splitlines() if not line.strip().startswith("#"))
    assert re.search(r"^\{\n\temail contact@ecoconsultancy\.services\n\tadmin unix//var/lib/caddy/admin\.sock\n\}",
                     body, re.MULTILINE)
    assert re.search(r"^@TOOL_DOMAIN@ \{$", body, re.MULTILINE)          # replaced by setup.sh
    for directive in ("encode gzip", "max_size 6MB", "reverse_proxy 127.0.0.1:8000",
                      '?Strict-Transport-Security "max-age=31536000"', "-Server"):
        assert directive in body, directive
    # The app sets CSP, frame, referrer and content-type headers itself: not repeated here.
    for header in ("Content-Security-Policy", "X-Frame-Options", "Referrer-Policy", "X-Content-Type-Options"):
        assert header.lower() not in body.lower(), header
    # Caddy's body limit sits just above the app's own upload limit.
    app_limit = Settings().max_upload_bytes + 64 * 1024
    assert app_limit < 6_000_000 < 2 * app_limit
    # setup.sh substitutes the domain, refuses a leftover placeholder and validates before use.
    setup = text(SETUP)
    assert '${template//@TOOL_DOMAIN@/$TOOL_DOMAIN}' in setup
    assert "grep -q '@TOOL_DOMAIN@' \"$new\" && die" in setup
    assert 'caddy validate --adapter caddyfile --config "$new"' in setup
    # The admin API moved from localhost:2019 to a socket: only a restart applies that.
    caddy_step = setup[setup.index("install_caddy() {"):setup.index("\n}\n", setup.index("install_caddy() {"))]
    assert "systemctl restart caddy" in caddy_step and "reload-or-restart caddy" not in caddy_step


def test_caddyfile_validates_with_caddy(tmp_path):
    caddy = shutil.which("caddy")
    if caddy is None:
        pytest.skip("caddy not installed (validated on the real server test)")
    rendered = tmp_path / "Caddyfile"
    rendered.write_text(text(KIT / "Caddyfile").replace("@TOOL_DOMAIN@", "tools.example.com"), encoding="utf-8")
    result = run([caddy, "validate", "--adapter", "caddyfile", "--config", str(rendered)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ----------------------------------------------------------------------------
# Settings template
# ----------------------------------------------------------------------------


def test_env_template_has_every_production_setting_and_no_fixed_secret(tmp_path, monkeypatch):
    template = text(KIT / "terrain-tool.env.template")
    values = env_lines(template)
    assert values["APP_ENV"] == "production"
    assert values["BASE_URL"] == "https://@TOOL_DOMAIN@"
    assert values["DATA_DIR"] == "/var/lib/terrain-tool"
    assert values["HOST"] == "127.0.0.1" and values["PORT"] == "8000"
    assert values["TRUST_PROXY_HEADERS"] == "true" and values["TRUSTED_PROXY_HOPS"] == "1"
    assert values["MAIL_BACKEND"] == "ses" and values["SES_REGION"] == "ap-southeast-5"
    assert values["MAIL_FROM"] == "EcoEnergy Consultancy <no-reply@ecoconsultancy.services>"
    assert values["MAIL_REPLY_TO"] == "contact@ecoconsultancy.services"
    assert values["ADMIN_USER"] == "admin"
    # Secrets are placeholders filled with random values on the server, never fixed in git.
    assert values["SECRET_KEY"] == "@SECRET_KEY@" and values["ADMIN_PASSWORD"] == "@ADMIN_PASSWORD@"
    assert "AWS_ACCESS_KEY_ID" not in values and "AWS_SECRET_ACCESS_KEY" not in values
    assert "# AWS_ACCESS_KEY_ID=" in template and "# AWS_SECRET_ACCESS_KEY=" in template
    # Every key is a real setting (or a process setting read by python -m app).
    fields = {name.upper() for name in Settings.__dataclass_fields__} - {"EXTRA"}
    assert set(values) <= fields | PROCESS_KEYS, set(values) - fields - PROCESS_KEYS

    # Rendered like setup.sh does it, the file starts the app in production mode.
    rendered = (template.replace("@TOOL_DOMAIN@", "tools.example.com")
                .replace("@SECRET_KEY@", "k" * 64).replace("@ADMIN_PASSWORD@", "p" * 24)
                .replace("DATA_DIR=/var/lib/terrain-tool", f"DATA_DIR={tmp_path / 'data'}"))
    env_file = tmp_path / "terrain-tool.env"
    env_file.write_text(rendered, encoding="utf-8")
    for key in fields | PROCESS_KEYS:
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env(env_file=env_file)
    assert not settings.is_dev and settings.secure_cookies
    assert settings.base_url == "https://tools.example.com"
    assert settings.mail_backend == "ses" and settings.trust_proxy_headers and settings.trusted_proxy_hops == 1
    assert settings.admin_password == "p" * 24 and settings.secret_key == "k" * 64
    assert settings.notice_version == Settings().notice_version


# ----------------------------------------------------------------------------
# The owner's guide
# ----------------------------------------------------------------------------


def test_readme_commands_point_at_real_files_and_the_right_branch():
    guide = text(KIT / "README.md")
    main_readme = text(ROOT / "README.md")
    script_path = SETUP.relative_to(ROOT.parent).as_posix()          # terrain-tool/deploy/aws-lightsail/setup.sh
    before = f"curl -fsSL {RAW}/{PR_BRANCH}/{script_path} | sudo TOOL_REF={PR_BRANCH} bash"
    after = f"curl -fsSL {RAW}/main/{script_path} | sudo bash"
    for doc in (guide, main_readme):
        assert before in doc and after in doc
    # The same commands are in the script's own usage notes.
    assert after.replace("curl -fsSL", "#   curl -fsSL") in text(SETUP)
    assert before.replace("curl -fsSL", "#   curl -fsSL") in text(SETUP)
    # Every curl command in the guide uses an existing script path and a consistent ref.
    commands = re.findall(rf"{re.escape(RAW)}/(\S+?)/(terrain-tool/\S+) \| sudo (?:TOOL_REF=(\S+) )?bash", guide)
    assert len(commands) == 2
    for ref, path, env_ref in commands:
        assert (ROOT.parent / path).is_file(), path
        assert ref in ("main", PR_BRANCH) and (env_ref or "main") == ref
    # Every `sudo terrain-tool …` command in the guide exists in the helper.
    helper_commands = set(re.findall(r"^    ([a-z-]+)(?: \| [^)]*)?\) cmd_", text(HELPER), re.MULTILINE))
    used = set(re.findall(r"sudo terrain-tool ([a-z][a-z-]*)", guide))
    assert used and used <= helper_commands | {"help"}, used - helper_commands
    assert "update --ref main" in guide
    # The status command warns while the server follows a working branch rather than main.
    assert "WARNING: this server follows the branch" in text(HELPER)
    assert "sudo terrain-tool update --ref main" in text(SETUP)        # hint when a branch is gone
    # The maintainer table lists every file of the kit, and nothing else.
    table = guide[guide.index("## For the maintainer"):]
    listed = {name for cell in re.findall(r"^\| (`[^|]+`) \|", table, re.MULTILINE)
              for name in re.findall(r"`([^`]+)`", cell)}
    assert listed == {p.name for p in KIT.iterdir() if p.is_file()} - {"README.md"}, listed
    # Links from the guide to the main README resolve.
    for link in re.findall(r"\]\((\.\./\.\./README\.md)[^)]*\)", guide):
        assert (KIT / link).resolve().is_file()
    assert "(deploy/aws-lightsail/README.md)" in main_readme


def test_readme_owner_steps_in_a_safe_order():
    guide = text(KIT / "README.md")
    # Full sign-up (the simplified one cannot use opt-in regions such as Malaysia), paid plan.
    assert "https://signin.aws.amazon.com/signup?request_type=register" in guide
    assert "**Paid account plan**" in guide and "Supported opt-in Regions" in guide
    assert "may suggest enabling the Malaysia region" not in guide
    # No HTTPS on IPv6 (there is no AAAA record; it would only help dodge per-address limits).
    assert "do **not** add HTTPS there" in guide
    assert "IPv6 Firewall** section, add **HTTPS**" not in guide
    # Malaysia's DKIM targets, and Turnstile before production access, which comes before the merge.
    assert ".dkim.ap-southeast-5.amazonses.com" in guide and "abcd1234efgh.dkim.amazonses.com" not in guide
    assert guide.index("### E8. Turn on the human check") < guide.index("### E9. Ask AWS for production access")
    part_g = guide[guide.index("## Part G"):guide.index("## Part H")]
    assert part_g.index("Wait for SES production access") < part_g.index("Merge the pull request")
    assert "Ready for review" in part_g and "pull/11" in part_g
    assert f"{RAW}/{PR_BRANCH}/terrain-tool/tests/fixtures/hilly_site_pahang.kml" in part_g
    assert (ROOT / "tests" / "fixtures" / "hilly_site_pahang.kml").is_file()
    # Backups: the honest figure (snapshots also hold the database copies).
    assert "gone from these backups after 14 days" not in guide and "about **3 weeks**" in guide
    assert "8% service tax" in guide


def test_readme_iam_policy_allows_only_sending_from_the_tool_address():
    guide = text(KIT / "README.md")
    block = re.search(r"```json\n(.*?)```", guide, re.DOTALL).group(1)
    policy = json.loads("\n".join(line.removeprefix("   ") for line in block.splitlines()))
    (statement,) = policy["Statement"]
    assert statement["Effect"] == "Allow"
    assert sorted(statement["Action"]) == ["ses:SendEmail", "ses:SendRawEmail"]
    assert all(arn.startswith("arn:aws:ses:ap-southeast-5:") for arn in statement["Resource"])
    sender = re.search(r"<([^>]+)>", Settings().mail_from).group(1)
    assert sender in statement["Condition"]["StringLike"]["ses:FromAddress"]
    assert env_lines(text(KIT / "terrain-tool.env.template"))["MAIL_FROM"].endswith(f"<{sender}>")
