#!/usr/bin/env bash
# One-command local run (macOS / Linux). Needs Python 3.11+.
# On a Mac you can simply double-click START-MAC.command instead.
set -euo pipefail
cd "$(dirname "$0")"

fail() {
  echo
  echo "  ERROR: $*"
  echo
  exit 1
}

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || fail "Python 3 was not found. Install Python 3.11 or newer from https://www.python.org/downloads/ and run this again."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "This needs Python 3.11 or newer, but '$PY' is $("$PY" -c 'import platform; print(platform.python_version())' 2>/dev/null || echo older). Install the latest Python from https://www.python.org/downloads/ and run this again."

# Check for the activate script, not just the folder: a failed "venv" run (e.g. Debian/Ubuntu
# without the python3-venv package) leaves a half-made .venv behind.
if [ ! -f .venv/bin/activate ]; then
  rm -rf .venv
  echo "  Setting up (first time only)…"
  "$PY" -m venv .venv || { rm -rf .venv; exit 1; }
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "  Installing or checking the required packages. The first run downloads about 150 MB"
echo "  and can take 5–10 minutes — please wait…"
python -m pip install --quiet --upgrade pip
# --prefer-binary: take the newest release with a wheel for this machine rather than a source
# release that needs GDAL to build (e.g. rasterio on macOS older than 15).
python -m pip install --quiet --prefer-binary -r requirements.txt

[ -f .env ] || cp .env.example .env

echo
echo "  Terrain screening tool  →  http://localhost:${PORT:-8000}"
echo "  Dev inbox (magic links) →  http://localhost:${PORT:-8000}/dev/outbox"
echo "  Admin (leads)           →  http://localhost:${PORT:-8000}/admin   (user/password from .env)"
echo
echo "  Leave this window open while you use the tool. Press Ctrl+C here to stop it."
echo
exec python -m app
