"""Deployment files and the process entry point: Docker image, compose stack, the one-command
run scripts and ``python -m app``."""
from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# Docker
# ----------------------------------------------------------------------------


def test_docker_image_has_the_system_library_rasterio_needs():
    """R1: rasterio's wheel links libexpat, which python:3.12-slim lacks; without it every
    copernicus/geotiff screening failed. The build installs it and fails if rasterio can't load."""
    dockerfile = text("Dockerfile")
    lines = [line.strip() for line in dockerfile.splitlines()]
    install = next(i for i, line in enumerate(lines) if "libexpat1" in line)
    pip = next(i for i, line in enumerate(lines) if line.startswith("RUN pip install"))
    check = next(i for i, line in enumerate(lines) if line.startswith("RUN python -c") and "import rasterio" in line)
    assert install < pip < check


def test_compose_publishes_on_loopback_only_and_waits_for_the_worker():
    """R10: the Mailpit inbox holds every magic link; R3: give a running job time to finish;
    R5: an .env copied from .env.example must not narrow the container's listen address."""
    compose = text("docker-compose.yml")
    published = re.findall(r'^\s*-\s*"([^"]+)"', compose, re.MULTILINE)
    assert published and all(p.startswith("127.0.0.1:") for p in published), published
    assert not any(p.endswith(":1025") for p in published)            # SMTP stays on the compose network
    grace = re.search(r"stop_grace_period:\s*(\d+)s", compose)
    assert grace and int(grace.group(1)) > 30                          # Worker.stop waits 30 s
    assert re.search(r"^\s*HOST:\s*0\.0\.0\.0\s*$", compose, re.MULTILINE)


# ----------------------------------------------------------------------------
# run_local.sh, exercised with a stand-in Python (no network, no real venv)
# ----------------------------------------------------------------------------

FAKE_PYTHON = r"""#!/bin/sh
# Stand-in for "python3 -m venv .venv": FAIL_VENV=1 behaves like Debian without python3-venv
# (a half-made .venv with only bin/python, then exit 1).
echo "base $*" >> "$RUN_LOG"
mkdir -p .venv/bin
if [ "$FAIL_VENV" = 1 ]; then
  ln -sf /bin/true .venv/bin/python
  echo "The virtual environment was not created successfully because ensurepip is not available." >&2
  exit 1
fi
cat > .venv/bin/python <<'EOF'
#!/bin/sh
echo "venv $*" >> "$RUN_LOG"
EOF
chmod +x .venv/bin/python
echo "PATH=\"$PWD/.venv/bin:\$PATH\"" > .venv/bin/activate
"""


@pytest.fixture
def run_local(tmp_path):
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    work = tmp_path / "tool"
    work.mkdir()
    shutil.copy(ROOT / "run_local.sh", work / "run_local.sh")
    (work / "requirements.txt").write_text("fastapi\n")
    (work / ".env.example").write_text("APP_ENV=development\n")
    fake = tmp_path / "fake-python3"
    fake.write_text(FAKE_PYTHON)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "run.log"

    def run(fail_venv: bool = False) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHON": str(fake), "RUN_LOG": str(log), "FAIL_VENV": "1" if fail_venv else "0"}
        return subprocess.run(["bash", str(work / "run_local.sh")], cwd=work, env=env, check=False,
                              capture_output=True, text=True, timeout=60)

    run.work, run.log = work, log
    return run


def test_run_local_recovers_from_a_failed_venv_creation(run_local):
    """R7: after the "install python3-venv" error, rerunning the script must work instead of
    failing on a half-made .venv for ever."""
    first = run_local(fail_venv=True)
    assert first.returncode != 0
    assert not (run_local.work / ".venv").exists()                    # nothing half-made left behind

    # A half-made .venv from an older version of the script is repaired too.
    (run_local.work / ".venv" / "bin").mkdir(parents=True)
    (run_local.work / ".venv" / "bin" / "python").symlink_to("/bin/true")
    second = run_local()
    assert second.returncode == 0, second.stderr
    assert (run_local.work / ".venv" / "bin" / "activate").is_file()
    assert (run_local.work / ".env").is_file()


def test_run_local_prefers_binary_wheels(run_local):
    """R4: on macOS < 15 the newest rasterio has only an sdist that needs GDAL to build; pip
    must take the newest release with a wheel instead."""
    assert run_local().returncode == 0
    calls = run_local.log.read_text().splitlines()
    assert "venv -m pip install --quiet --prefer-binary -r requirements.txt" in calls
    assert calls[-1] == "venv -m app"


def test_windows_script_and_instructions():
    """R8: Windows blocks .ps1 files by default, and PowerShell 5.1 ignores native exit codes;
    R4 / R7 as for the shell script."""
    ps1 = text("run_local.ps1")
    readme = text("README.md")
    assert r"powershell -ExecutionPolicy Bypass -File .\run_local.ps1" in readme
    assert "--prefer-binary -r requirements.txt" in ps1
    assert r"Test-Path .venv\Scripts\python.exe" in ps1
    native = [i for i, line in enumerate(ps1.splitlines())
              if re.search(r"(^|\s)(py -3 -m venv|& \.\\\.venv\\Scripts\\python\.exe -m pip)", line)]
    lines = ps1.splitlines()
    assert len(native) == 3
    for i in native:
        assert "$LASTEXITCODE" in lines[i + 1], lines[i]


# ----------------------------------------------------------------------------
# python -m app
# ----------------------------------------------------------------------------


def test_process_settings_come_from_dotenv_too(tmp_path, monkeypatch):
    """R5: HOST, PORT and LOG_LEVEL set in .env (as .env.example documents) are honoured;
    real environment variables still win."""
    from app import __main__ as entry

    for key in ("HOST", "PORT", "LOG_LEVEL", "BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("HOST=0.0.0.0\nPORT=8123\nLOG_LEVEL=warning\n")
    proc = entry.process_settings(env_file)
    assert proc == {"host": "0.0.0.0", "port": 8123, "log_level": "WARNING", "base_url_set": False}
    monkeypatch.setenv("PORT", "9001")
    assert entry.process_settings(env_file)["port"] == 9001
    assert entry.process_settings(tmp_path / "missing.env")["port"] == 9001
    monkeypatch.delenv("PORT")
    assert entry.process_settings(tmp_path / "missing.env") == {
        "host": "127.0.0.1", "port": 8000, "log_level": "INFO", "base_url_set": False}


def test_email_links_follow_the_listen_port(tmp_path, caplog):
    """R6: with PORT changed, links built from BASE_URL must point at the port the app uses."""
    from app.__main__ import align_base_url
    from app.config import Settings

    s = Settings(data_dir=tmp_path)
    assert align_base_url(s, 8111, base_url_set=False).base_url == "http://localhost:8111"
    with caplog.at_level(logging.WARNING, logger="app.__main__"):
        kept = align_base_url(s, 8111, base_url_set=True)
    assert kept.base_url == "http://localhost:8000" and "listens on port 8111" in caplog.text
    caplog.clear()
    prod = Settings(data_dir=tmp_path, base_url="https://tools.example.com")
    with caplog.at_level(logging.WARNING, logger="app.__main__"):
        assert align_base_url(prod, 8000, base_url_set=True) is prod
    assert caplog.text == ""
    env_example = text(".env.example")
    assert not re.search(r"^BASE_URL=", env_example, re.MULTILINE)   # commented out: follows PORT


def test_ctrl_c_stops_without_a_traceback(tmp_path, monkeypatch):
    """R11: uvicorn re-raises the captured SIGINT after a clean shutdown; python -m app must
    exit quietly, as uvicorn.run() does."""
    import uvicorn

    from app import __main__ as entry
    from app.config import Settings

    def interrupted(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(uvicorn.Server, "run", interrupted)
    monkeypatch.setattr(entry, "get_settings", lambda: Settings(data_dir=tmp_path, worker_inline=False))
    monkeypatch.setattr(entry, "create_app", lambda settings: object())
    monkeypatch.setattr(entry, "process_settings",
                        lambda env_file=None: {"host": "127.0.0.1", "port": 8000, "log_level": "INFO",
                                               "base_url_set": True})
    entry.main()                                      # returns instead of raising KeyboardInterrupt


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell test")
def test_shell_script_is_executable():
    assert os.access(ROOT / "run_local.sh", os.X_OK)
