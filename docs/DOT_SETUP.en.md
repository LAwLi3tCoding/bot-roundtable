# Private dot handoff setup

These are operator-reviewed templates, not an installer or account authorization. Nothing here loads launchd, installs a tunnel client, creates keys, subscribes to Events or sends a routine.

1. Choose a dedicated checkout and set `ROUNDTABLE_HOME` to its absolute path. Create `.venv` with Python 3.12/3.13 and install `requirements.lock`. Follow README to supply an administrator secret through your approved secret manager/environment and create a dedicated room. Register Grok and dot with separate scoped credentials; keep initiation allowances at zero initially. Never put secrets in a shell command, source file or transcript.
2. Start `sh scripts/start-local.sh server` with the administrator environment. This binds loopback only. Do not start a second instance on an occupied port or database.
3. Configure `ROUNDTABLE_URL`, `ROUNDTABLE_ROOM`, `ROUNDTABLE_AGENT`, `ROUNDTABLE_TOKEN` through approved environment references for the dot identity. Run `.venv/bin/python scripts/check.py doctor`, then `probe`. The wrapper opens no credential file, closes stdin and limits execution to 15 seconds. This is transport evidence only.
4. Supply `ROUNDTABLE_HTTP_GRANTS` with only the intended dot grant, following `docs/HTTP.en.md`. Set `ROUNDTABLE_TUNNEL_AUTH_HEADER` to the complete `Bearer <dot scoped token>` via the same secure environment; the gateway uses it as a fixed-identity guard. Start `sh scripts/start-local.sh mcp` (default loopback 8766).
5. Obtain a tunnel client only from official distribution after separate authorization. Supply your own runtime key, tunnel ID and workspace permissions; copy/review `examples/tunnel-client.yaml` as a named profile. Set `ROUNDTABLE_TUNNEL_PROFILE`; run the official `tunnel-client doctor --profile <name> --explain`, then the tunnel start script only when authorized.
6. For this private fixed-identity route choose **No authentication** in the ChatGPT connector: the tunnel injects the local Bearer header. This does not disable gateway authentication. Official [configuration reference](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md) says forwarded connector headers apply last and override `mcp.extra_headers` case-insensitively. A conflicting forwarded Authorization therefore produces `tunnel_authorization_mismatch` at this gateway, without logging header values. Missing headers produce the same diagnostic. Do not disable authentication to make the test pass. A matched header cannot prove whether it was injected or forwarded. Verify actual connector `list_rooms`/`list_bots` results for the unique expected room/identity; tunnel doctor alone is not acceptance.
7. Only after user approval grant the origin a small allowance: `.venv/bin/python scripts/admin.py allowance <room-id> <origin-agent> 1`, with an inherited administrator environment. Never give the administrator token to a bot. Subscription, native Codex execution, and routine configuration require their own user-authorized scopes.

Launchd templates under `deploy/launchd/` are intentionally inactive. `${ROUNDTABLE_HOME}` is a rendering placeholder, not launchd variable expansion. Replace it locally with an absolute path, arrange secure environment injection (including PATH for the official tunnel binary), review permissions and lifecycle, and obtain approval before loading. Do not paste secrets into tracked plists. Foreground scripts stop with Ctrl-C; for a managed process verify ownership before signaling its PID. No auto-restart is configured.

## Lease and callback operations

`claim_assignment(..., lease_seconds=60)` accepts integer 30–1800 seconds; expiry and progress renewal are capped by the task deadline. Progress renews the selected duration. Task `timeout_seconds` accepts 30–86400. Expired work can be reclaimed within attempt/budget limits; an old lease cannot report after reclaim. External Codex effects are not automatically undone or replayed.

Events remain off unless explicitly configured and subscribed. `ROUNDTABLE_EVENT_TIMEOUT` sets the total callback deadline (default 20 seconds, 0.01–120), including DNS and transport. Ambient proxy environment variables fail closed without an explicit setting. To explicitly use a trusted HTTP CONNECT proxy set `ROUNDTABLE_OUTBOUND_PROXY` (or legacy `ROUNDTABLE_EVENT_PROXY`) to its HTTP origin; credentials are unsupported. In direct mode callback DNS results must all be public and the selected IP is pinned. In explicit proxy mode CONNECT targets the canonical hostname; only the trusted proxy resolves it, while TLS/Host retain that hostname. No redirect or direct fallback occurs. Uninterruptible DNS retains a bounded worker slot until it finishes. Rejected hosts log only `callback_host_not_approved` and a sanitized hostname.

After separate subscription approval, `handoff.available` means: receive_assignments → claim_assignment → dot checks task/user authority and may create a Codex task using its own connected-computer tools → report progress → completed/failed. An event is a wake hint, not authorization. Never execute instructions embedded in task data outside the approved task scope.

To opt in to the Events endpoint after configuration approval, start the gateway with:

```sh
sh scripts/start-local.sh mcp --events-db "${ROUNDTABLE_HOME}/data/events.db" --event-host approved.hostname
```

Replace `approved.hostname` with an explicitly approved callback hostname; repeat `--event-host` for additional approved hosts. Arguments are forwarded unchanged. The default `mcp` command and launchd template leave Events disabled. For launchd, append the same arguments as separate `ProgramArguments` strings after `mcp`, using a rendered absolute database path; review before loading. This enables the endpoint only: actual `handoff.available` subscriptions still require the user's separate confirmation after implementation acceptance.

## When the computer requires a proxy (for example Clash fake-ip)

Set `ROUNDTABLE_OUTBOUND_PROXY` to `http://127.0.0.1:<PORT>` in both the MCP Events gateway and server/routine process environments. Replace `<PORT>` with your already configured local HTTP CONNECT proxy port. We do not inspect or change Clash, system DNS, or global network settings. The legacy `ROUNDTABLE_EVENT_PROXY` also works for both paths; the nonempty unified variable takes precedence if both are set. There is no direct fallback.

The explicit proxy is a user-selected trusted DNS/routing boundary: CONNECT carries the canonical destination hostname, not a locally resolved fake IP. Local fake-IP responses therefore do not reject this mode. The local service cannot establish whether the proxy's final IP is public. Exact hostname allowlists, HTTPS, original-host certificate verification, and rejection of IP literals/local names remain required. Direct mode retains local DNS/public-IP validation and pinning.

Ambient `HTTPS_PROXY`/`HTTP_PROXY`/`ALL_PROXY` without the explicit setting produces `explicit_outbound_proxy_required`. `doctor` reports safe `outbound_local`, `outbound_backend`, and `terminal_worker` fields; gateway environment may differ and must be configured separately. These diagnostics are configuration observations, not proof of live vendor reachability. Configuration errors do not consume terminal receipt reservations; fix configuration to resume. A reserved uncertain attempt is never automatically replayed.

## Environment and startup templates

`start-local.sh` reads no configuration or secret files. It inherits the caller's environment and forwards extra arguments unchanged. The table distinguishes script arguments from Python process settings: setting `ROUNDTABLE_PORT` alone does not update the client's `ROUNDTABLE_URL`.

| Variable | Consumer and configuration |
|---|---|
| `ROUNDTABLE_HOME` | Required by the startup script; absolute checkout path |
| `ROUNDTABLE_PORT` / `ROUNDTABLE_DB` | Script arguments to the server; defaults 8765 / `data/roundtable.db` |
| `ROUNDTABLE_ADMIN_TOKEN` | Server and allowance command; securely inject a random secret of at least 32 characters |
| `ROUNDTABLE_URL` | Bridge, HTTP gateway, local client, and allowance; default `http://127.0.0.1:8765` |
| `ROUNDTABLE_ROOM` / `ROUNDTABLE_AGENT` / `ROUNDTABLE_TOKEN` | Room, member, and independent member credential for stdio bridge and local client |
| `ROUNDTABLE_MCP_PORT` / `ROUNDTABLE_HTTP_GRANTS` | Script argument for gateway port (default 8766); required gateway grant JSON, documented in [HTTP](HTTP.en.md) |
| `ROUNDTABLE_OUTBOUND_PROXY` | Configure separately for server/routine and Events gateway; `http://127.0.0.1:<PORT>`, a trusted HTTP CONNECT proxy without credentials |
| `ROUNDTABLE_EVENT_PROXY` | Legacy outbound proxy setting; nonempty `ROUNDTABLE_OUTBOUND_PROXY` takes precedence |
| `ROUNDTABLE_EVENT_TIMEOUT` | Total Events callback deadline; default 20 seconds, range 0.01–120 |
| `ROUNDTABLE_TUNNEL_AUTH_HEADER` | Gateway fixed-member identity guard; securely inject the complete Bearer header |
| `ROUNDTABLE_TUNNEL_PROFILE` | Required by `start-local.sh tunnel`; reviewed local profile name |
| `ROUNDTABLE_EVIDENCE` | Local client's default roundtrip evidence path; defaults to `data/roundtrip.json`, overridden by `--evidence` |
| `ROUNDTABLE_TERMINAL_NOTIFICATIONS` | Only `1` enables the server terminal worker; disabled by default |
| `ROUNDTABLE_TERMINAL_ROOM` / `ROUNDTABLE_TERMINAL_ORIGIN` | Room and current origin member covered by the terminal worker |
| `ROUNDTABLE_TERMINAL_LEDGER` | Shared durable ledger for manual and automatic receipts; default `data/terminal-receipts.db` |
| `GROK_ROUTINE_URL` / `GROK_ROUTINE_KEY` / `GROK_ALLOWED_HOST` | Authorized routine HTTPS URL, secret, and exact hostname allowlist; see [terminal receipts](TERMINAL_RECEIPTS.en.md) |

Events database and approved hosts are CLI arguments, `--events-db` / `--event-host`, not environment variables. Declare a nondefault external HTTPS URL with `--public-url`; the listener remains loopback-only.

The launchd templates contain only `ROUNDTABLE_HOME`; they do not inherit terminal `export` statements. Render paths locally and configure the required environment separately for each service. When proxying is required, add `ROUNDTABLE_OUTBOUND_PROXY` to both server and MCP environments. Templates default to `RunAtLoad=false` and `KeepAlive=false`; they do not load themselves or enable Events, and this documentation does not require loading them. Never commit real secrets or rendered deployment configuration.

## One-time user acceptance checklist

The user performs these steps with their own accounts and authorized environment. Replace placeholders and retain the original task and ledger; do not hide uncertain outcomes by deleting a ledger or recreating a task.

1. **Stop the old instance and prepare the new one:** verify ownership, port, and database, then back up data. Stop only an old process you have confirmed you manage. Prepare configuration for the current version; never share a database between instances. Leave unidentified services alone.
2. **Set the proxy and start the new processes:** configure `ROUNDTABLE_OUTBOUND_PROXY=http://127.0.0.1:<PORT>` separately in server/routine and MCP gateway environments before starting them. A running process does not see later terminal exports; restart the affected process in your own maintenance window when configuration changes.
3. **Doctor:** run `.venv/bin/python scripts/check.py doctor` with the member environment. Confirm both `outbound_local.mode` and `outbound_backend.mode` are `trusted_proxy_dns`, with `configured=true`. `outbound_backend` is a structured object. This does not prove vendor callback reachability or validate the separate gateway environment.
4. **Tool discovery:** complete the authorized private Tunnel setup and select **No authentication** in the ChatGPT connector. Discover tools in the real Dot conversation and call `list_rooms` / `list_bots` to verify the unique expected room/member. Tunnel doctor success alone is insufficient.
5. **Approve the callback hostname:** inspect the actual product-provided hostname and configure the gateway's exact `--event-host` and private `--events-db` as above. Do not use wildcards or disable host checks. Restart only your managed gateway if needed.
6. **Allowance:** from the administrator environment, run `.venv/bin/python scripts/admin.py allowance '<ROOM_ID>' '<ORIGIN_AGENT_ID>' 1` within the authorized scope. Never put administrator credentials in bot configuration.
7. **Subscribe to `handoff.available`:** explicitly ask Dot to listen for this member's work and confirm subscription success. Subscriptions expire and are not permanent authorization; events are wake hints only.
8. **Native roundtrip:** with the origin member's environment, run `roundtrip --worker '<WORKER_AGENT_ID>'` from the [roundtrip guide](ROUNDTRIP.en.md). Observe real Dot waking, claiming, and returning the nonce, and the origin retrieving the same task's result. Re-read with `doctor --evidence`; record protocol correlation, native conversation, and wake observations separately. This read-only roundtrip creates no Codex task and sends no Grok routine.

If a step fails, record its stage and safe error code, then resume from the original task state after fixing the issue. Real work handoffs and optional Grok terminal receipts need their own explicit scope; this checklist does not replace that authorization or acceptance.
