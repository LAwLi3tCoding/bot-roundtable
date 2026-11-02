#!/bin/sh
set -eu
# Inherit operator-provided environment, including ROUNDTABLE_OUTBOUND_PROXY.
# No credential files are loaded; see docs/DOT_SETUP.en.md for configuration.
: "${ROUNDTABLE_HOME:?Set project directory}"
cd "$ROUNDTABLE_HOME"
component="${1:-}"
if [ "$#" -gt 0 ]; then shift; fi
case "$component" in
  server) exec "$ROUNDTABLE_HOME/.venv/bin/python" server.py --port "${ROUNDTABLE_PORT:-8765}" --db "${ROUNDTABLE_DB:-$("$ROUNDTABLE_HOME/.venv/bin/python" -c 'from state_paths import state_dir; print(state_dir() / "roundtable.db")')}" "$@" ;;
  mcp) exec "$ROUNDTABLE_HOME/.venv/bin/python" mcp_http.py --port "${ROUNDTABLE_MCP_PORT:-8766}" "$@" ;;
  tunnel)
    if [ -n "${ROUNDTABLE_TUNNEL_PROFILE_FILE:-}" ]; then
      set -- --profile-file "$ROUNDTABLE_TUNNEL_PROFILE_FILE" "$@"
    else
      : "${ROUNDTABLE_TUNNEL_PROFILE:?Set profile name or ROUNDTABLE_TUNNEL_PROFILE_FILE}"
      set -- --profile "$ROUNDTABLE_TUNNEL_PROFILE" "$@"
    fi
    if [ -n "${ROUNDTABLE_OUTBOUND_PROXY:-}" ]; then
      set -- --control-plane.http-proxy "$ROUNDTABLE_OUTBOUND_PROXY" "$@"
    fi
    unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
    exec tunnel-client run "$@" ;;
  *) echo 'Usage: start-local.sh server|mcp|tunnel [arguments...]' >&2; exit 2 ;;
esac
