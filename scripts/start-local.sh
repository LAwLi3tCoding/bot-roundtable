#!/bin/sh
set -eu
# Inherit operator-provided environment, including ROUNDTABLE_OUTBOUND_PROXY.
# No credential files are loaded; see docs/DOT_SETUP.en.md for configuration.
: "${ROUNDTABLE_HOME:?Set project directory}"
cd "$ROUNDTABLE_HOME"
component="${1:-}"
if [ "$#" -gt 0 ]; then shift; fi
case "$component" in
  server) exec "$ROUNDTABLE_HOME/.venv/bin/python" server.py --port "${ROUNDTABLE_PORT:-8765}" --db "${ROUNDTABLE_DB:-data/roundtable.db}" "$@" ;;
  mcp) exec "$ROUNDTABLE_HOME/.venv/bin/python" mcp_http.py --port "${ROUNDTABLE_MCP_PORT:-8766}" "$@" ;;
  tunnel) : "${ROUNDTABLE_TUNNEL_PROFILE:?Set reviewed profile name}"; exec tunnel-client run --profile "$ROUNDTABLE_TUNNEL_PROFILE" "$@" ;;
  *) echo 'Usage: start-local.sh server|mcp|tunnel [arguments...]' >&2; exit 2 ;;
esac
