#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required")
print(f"Python {sys.version.split()[0]} OK")
PY

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON_BIN" -m compileall -q src tests
"$PYTHON_BIN" -m unittest discover -s tests -v
"$PYTHON_BIN" -m trendgpt.cli --help >/dev/null
"$PYTHON_BIN" -m trendgpt.adjudicate --help >/dev/null
"$PYTHON_BIN" -m trendgpt.dispatch_intent --help >/dev/null

echo "Offline port check passed. No network requests were made by this script."
