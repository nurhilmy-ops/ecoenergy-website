#!/usr/bin/env bash
# One-command local run (macOS / Linux). Needs Python 3.11+.
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
# Check for the activate script, not just the folder: a failed "venv" run (e.g. Debian/Ubuntu
# without the python3-venv package) leaves a half-made .venv behind.
if [ ! -f .venv/bin/activate ]; then
  rm -rf .venv
  "$PY" -m venv .venv || { rm -rf .venv; exit 1; }
fi
# shellcheck disable=SC1091
source .venv/bin/activate
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
exec python -m app
