#!/usr/bin/env bash
# GeoLock one-time setup for Linux/macOS.  ./setup.sh [--int8] [--vlm]
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
[ -d .venv ] || "$PY" -m venv .venv
EXTRAS=setup
for a in "$@"; do [ "$a" = "--vlm" ] && EXTRAS=setup,vlm; done
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[$EXTRAS]"
.venv/bin/python -m pip install geoclip --no-deps
.venv/bin/python -m geolock.setup_models "$@"
echo "Done. Start with: .venv/bin/python -m geolock"
