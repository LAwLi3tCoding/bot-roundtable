#!/bin/sh
# Check prerequisites, create .venv and install pinned dependencies.
# Usage: sh scripts/install.sh [--check]
# --check only reports what is missing and changes nothing.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CHECK=0
case "${1:-}" in
  --check) CHECK=1 ;;
  '') ;;
  *) echo 'Usage: sh scripts/install.sh [--check]' >&2; exit 2 ;;
esac

supported() {
  "$1" -c 'import sys; raise SystemExit(sys.version_info[:2] not in ((3, 12), (3, 13)))' 2>/dev/null
}

PY=''
for candidate in ${ROUNDTABLE_INSTALL_PYTHON:-} python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && supported "$candidate"; then
    PY=$(command -v "$candidate")
    break
  fi
done
if [ -z "$PY" ]; then
  echo 'missing: Python 3.12 or 3.13 (macOS: brew install python@3.12)' >&2
  exit 3
fi
echo "ok: python $("$PY" -c 'import platform; print(platform.python_version())')"

case "$(uname -s)" in
  Darwin|Linux) echo "ok: platform $(uname -s)" ;;
  *) echo 'missing: macOS or Linux (Windows process management is not supported)' >&2; exit 3 ;;
esac

case "$ROOT" in
  "$HOME"/Documents/*|"$HOME"/Desktop/*|"$HOME"/Downloads/*)
    if [ "$(uname -s)" = Darwin ]; then
      echo 'warning: checkout is in a macOS protected folder; prefer ~/code/bot-roundtable' >&2
    fi ;;
esac

if [ "$CHECK" = 1 ]; then
  if [ -x "$ROOT/.venv/bin/python" ] && supported "$ROOT/.venv/bin/python"; then
    echo 'ok: .venv'
  else
    echo 'todo: .venv (run sh scripts/install.sh)'
  fi
  exit 0
fi

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  "$PY" -m venv "$ROOT/.venv"
fi
if ! supported "$ROOT/.venv/bin/python"; then
  echo 'error: existing .venv is not Python 3.12/3.13; move it aside and rerun' >&2
  exit 3
fi
"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check -q -r "$ROOT/requirements.lock"
echo 'ok: dependencies installed'
echo 'next: .venv/bin/python scripts/setup-local.py --origin grok --worker dot'
