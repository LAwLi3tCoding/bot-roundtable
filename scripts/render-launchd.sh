#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "${ROUNDTABLE_PYTHON:-$ROOT/.venv/bin/python}" "$ROOT/scripts/local_runtime.py" render-launchd "$@"
