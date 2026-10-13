#!/usr/bin/env bash
# One-command local run (macOS / Linux). Needs Python 3.11+.
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

[ -f .env ] || cp .env.example .env

echo
echo "  Terrain screening tool  →  http://localhost:${PORT:-8000}"
echo "  Dev inbox (magic links) →  http://localhost:${PORT:-8000}/dev/outbox"
echo "  Admin (leads)           →  http://localhost:${PORT:-8000}/admin   (user/password from .env)"
echo
exec python -m app
