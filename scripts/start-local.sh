#!/bin/sh
set -eu
: "${ROUNDTABLE_HOME:?Set project directory}"
cd "$ROUNDTABLE_HOME"
case "${1:-}" in
  server) exec "$ROUNDTABLE_HOME/.venv/bin/python" server.py --port "${ROUNDTABLE_PORT:-8765}" --db "${ROUNDTABLE_DB:-data/roundtable.db}" ;;
  mcp) exec "$ROUNDTABLE_HOME/.venv/bin/python" mcp_http.py --port "${ROUNDTABLE_MCP_PORT:-8766}" ;;
  tunnel) : "${ROUNDTABLE_TUNNEL_PROFILE:?Set reviewed profile name}"; exec tunnel-client run --profile "$ROUNDTABLE_TUNNEL_PROFILE" ;;
  *) echo 'Usage: start-local.sh server|mcp|tunnel' >&2; exit 2 ;;
esac
