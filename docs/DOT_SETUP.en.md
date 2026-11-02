# Private dot handoff setup

For new installations, use [managed local setup](SETUP_AUTOMATION.en.md). The manual commands below remain an alternative; do not run both managers on one instance.


The manual route below uses operator-reviewed templates; the linked managed setup automates local files and processes, not account authorization. Nothing here loads launchd, installs a tunnel client, creates keys, subscribes to Events or sends a routine.

1. Choose a dedicated checkout and set `ROUNDTABLE_HOME` to its absolute path. Create `.venv` with Python 3.12/3.13 and install `requirements.lock`. Follow README to supply an administrator secret through your approved secret manager/environment and create a dedicated room. Register Grok and dot with separate scoped credentials; keep initiation allowances at zero initially. Never put secrets in a shell command, source file or transcript.
2. Start `sh scripts/start-local.sh server` with the administrator environment. This binds loopback only. Do not start a second instance on an occupied port or database.
3. Configure `ROUNDTABLE_URL`, `ROUNDTABLE_ROOM`, `ROUNDTABLE_AGENT`, `ROUNDTABLE_TOKEN` through approved environment references for the dot identity. Run `.venv/bin/python scripts/check.py doctor`, then `probe`. The wrapper opens no credential file, closes stdin and limits execution to 15 seconds. This is transport evidence only.
4. Supply `ROUNDTABLE_HTTP_GRANTS` with only the intended dot grant, following `docs/HTTP.en.md`. Set `ROUNDTABLE_TUNNEL_AUTH_HEADER` to the complete `Bearer <dot scoped token>` via the same secure environment; the gateway uses it as a fixed-identity guard. Start `sh scripts/start-local.sh mcp` (default loopback 8766).
5. Follow “Verified Platform, Tunnel, and ChatGPT setup” below for the official client, restricted runtime key, workspace binding, and profile-file commands. These remain one-time operator steps.
6. For this private fixed-identity route choose **No authentication** in the ChatGPT connector: the tunnel injects the local Bearer header. This does not disable gateway authentication. Official [configuration reference](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md) says forwarded connector headers apply last and override `mcp.extra_headers` case-insensitively. A conflicting forwarded Authorization therefore produces `tunnel_authorization_mismatch` at this gateway, without logging header values. Missing headers produce the same diagnostic. Do not disable authentication to make the test pass. A matched header cannot prove whether it was injected or forwarded. Verify actual connector `list_rooms`/`list_bots` results for the unique expected room/identity; tunnel doctor alone is not acceptance.
7. Only after user approval grant the origin a small allowance: `.venv/bin/python scripts/admin.py allowance <room-id> <origin-agent> 1`, with an inherited administrator environment. Never give the administrator token to a bot. Subscription, native Codex execution, and routine configuration require their own user-authorized scopes.

Launchd templates under `deploy/launchd/` are intentionally inactive. `${ROUNDTABLE_HOME}` is a rendering placeholder, not launchd variable expansion. Replace it locally with an absolute path, arrange secure environment injection (including PATH for the official tunnel binary), review permissions and lifecycle, and obtain approval before loading. Do not paste secrets into tracked plists. Foreground scripts stop with Ctrl-C; for a managed process verify ownership before signaling its PID. No auto-restart is configured.

## Starting from zero: prerequisites and local identities

You need Git, Python 3.12/3.13, a local computer that can stay running, and a browser. Shell, permissions, and manual process commands here target macOS/Linux; Windows requires equivalent current-user ACLs and process management and was not part of this live test. Local demos need no vendor account. Private cloud access also requires a Platform organization with Tunnel creation access, a bindable ChatGPT workspace, and product support for custom MCP/Tunnel and Events. Verify those controls are actually available; do not assume every account or plan supports them.

```sh
git clone '<REPOSITORY_URL>' '<CHECKOUT_DIRECTORY>'
export ROUNDTABLE_HOME='<CHECKOUT_DIRECTORY>'
cd "${ROUNDTABLE_HOME}"
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
umask 077
mkdir -p data
chmod 700 data
export ROUNDTABLE_PORT='<SERVER_PORT>'
export ROUNDTABLE_URL='http://127.0.0.1:<SERVER_PORT>'
export ROUNDTABLE_DB="${ROUNDTABLE_HOME}/data/roundtable.db"
```

Use an absolute checkout path and the same server port in both settings. Repeat the non-secret path/port settings in later terminals. Do not clone or recreate an existing environment unnecessarily. Retain any proxy needed to install dependencies without changing global networking. Obtain the Tunnel client for your OS/architecture from [official releases](https://github.com/openai/tunnel-client/releases), verify its source following official instructions, and install it on PATH. Check `tunnel-client --version` first; an existing compatible installation need not be replaced. The Tunnel steps below were exercised with 0.0.19.

Generate and retain the administrator secret in a trusted password manager (at least 32 random characters). If you have no process-level secret injector, this interactive local example starts the server with hidden input. The secret stays out of command text and shell history and is passed only to the child process. Unavailable hidden input fails instead of falling back to visible input:

```sh
cd "${ROUNDTABLE_HOME}"
.venv/bin/python -c 'import getpass, os, warnings; warnings.simplefilter("error", getpass.GetPassWarning); os.environ["ROUNDTABLE_ADMIN_TOKEN"] = getpass.getpass("Administrator secret (hidden): "); os.execvp("sh", ["sh", "scripts/start-local.sh", "server"])'
```

Leave the foreground server running and open its local `ROUNDTABLE_URL` in the browser. Choose Connect and enter the administrator secret. Register two non-demo bot identities and select them when creating a dedicated room (or add registered identities to that room). Retain the displayed room ID, agent IDs, and each **agent token** in your password manager. Never give bots the owner/room token or administrator secret. Do not screenshot/share the secret display. Each member/room binding has a separate token; if lost, remove and re-add that member to obtain a new credential and update the affected gateways. Old tokens cannot be recovered from their stored digests.

In another terminal, set dot's `export ROUNDTABLE_ROOM='<ROOM_ID>'`, `export ROUNDTABLE_AGENT='<DOT_AGENT_ID>'`, and `export ROUNDTABLE_MCP_PORT='<MCP_PORT>'`. Do not swap the two identities' tokens. Receiving work needs no initiation allowance; only the roundtrip origin needs one unit.

Local doctor with hidden input (replace the final `doctor` with `probe` for a connection observation; probe writes an observation but creates no task):

```sh
.venv/bin/python -c 'import getpass, os, sys, warnings; warnings.simplefilter("error", getpass.GetPassWarning); os.environ["ROUNDTABLE_TOKEN"] = getpass.getpass("Member token (hidden): "); os.execv(sys.executable, [sys.executable, "scripts/check.py", "doctor"])'
```

Start a gateway granting only this dot identity as follows. Keep its foreground terminal open; do not start another listener on its port. Set the explicit outbound proxy described below first if needed:

```sh
.venv/bin/python -c 'import getpass, json, os, warnings; warnings.simplefilter("error", getpass.GetPassWarning); token = getpass.getpass("Dot member token (hidden): "); os.environ["ROUNDTABLE_HTTP_GRANTS"] = json.dumps([{"room": os.environ["ROUNDTABLE_ROOM"], "agent": os.environ["ROUNDTABLE_AGENT"], "token": token}]); os.environ["ROUNDTABLE_TUNNEL_AUTH_HEADER"] = "Bearer " + token; os.execvp("sh", ["sh", "scripts/start-local.sh", "mcp"])'
```

These are reviewable interactive examples, not a repository utility that saves/configures secrets. Later environment changes are not shared automatically across terminals. Tunnel doctor/run need their own `CONTROL_PLANE_API_KEY` and the same member's complete Bearer. For example, pass the command below to a hidden-input launcher:

```sh
.venv/bin/python -c 'import getpass, os, sys, warnings; warnings.simplefilter("error", getpass.GetPassWarning); os.environ["CONTROL_PLANE_API_KEY"] = getpass.getpass("Tunnel runtime key (hidden): "); os.environ["ROUNDTABLE_TUNNEL_AUTH_HEADER"] = "Bearer " + getpass.getpass("Dot member token (hidden): "); os.execvp(sys.argv[1], sys.argv[1:])' tunnel-client doctor --profile-file "${ROUNDTABLE_HOME}/data/tunnel/roundtable.yaml" --health.listen-addr 127.0.0.1:0 --explain
```

Complete the profile/key setup below before running this example. To run the Tunnel, replace its trailing `tunnel-client doctor …` with the full `tunnel-client run …` command below; append the control-plane proxy option when required. The same `getpass` plus child-process approach can inject only the administrator variable for allowance commands, without pasting secrets into `export` statements. For unattended operation use your approved secret manager and protect access to process environments.

## Verified Platform, Tunnel, and ChatGPT setup

These commands were checked against the official `tunnel-client 0.0.19` help and configuration format. Product UI labels may change; verify the equivalent operation and its final state. The operator handles software installation and account permissions; this guide supplies no account or key provisioning automation. Local-only tool use can stop at step 4 above without Tunnel/Events.

1. **Create the Tunnel.** In [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels), verify the account and organization and check for an existing target Tunnel before creating another. Set its name/description and authorize the intended organization and actual ChatGPT workspace. Retain the Tunnel ID. Grant only the intended workspace; matching email addresses do not establish workspace binding.
2. **Create a least-privilege runtime key.** In [API keys](https://platform.openai.com/settings/organization/api-keys), select the intended project, name the key, choose **Restricted**, and enable only **Tunnels Read and Use**. All other permissions remain None; grant neither Manage nor model access. Choose an expiry deliberately and assign renewal responsibility. If these exact scopes are unavailable, stop and verify support instead of substituting an All/full-project key.
3. **Store it securely.** Use an approved secret manager or hidden local input to save the key and provide `CONTROL_PLANE_API_KEY` only to the Tunnel process. Restrict local files/directories to `600`/`700` under Git-ignored `data/`; check with `git check-ignore <path>`, not by printing secrets. Never put keys in command text, chat, screenshots, logs, tracked YAML/plists, or Codex's `OPENAI_API_KEY`. The member token is a different credential: securely inject the full scoped `Bearer …` into `ROUNDTABLE_TUNNEL_AUTH_HEADER`, matching the gateway's fixed dot member. This repository has no installer that reads or saves these secrets for you.
4. **Prepare a profile.** Supply the secure environment first, then create the private directory and copy the template:

```sh
umask 077
mkdir -p "${ROUNDTABLE_HOME}/data/tunnel"
chmod 700 "${ROUNDTABLE_HOME}/data/tunnel"
cp -n "${ROUNDTABLE_HOME}/examples/tunnel-client.yaml" "${ROUNDTABLE_HOME}/data/tunnel/roundtable.yaml"
chmod 600 "${ROUNDTABLE_HOME}/data/tunnel/roundtable.yaml"
```

Copy only on first setup when the destination does not exist; do not overwrite existing configuration. Edit `<TUNNEL_ID>` and the actual MCP port in the local copy. YAML uses a `mcp.server_urls` list with `channel: main` and `url`, not the old `server_url` field. `env:VARIABLE` is a supported secret reference; do not assume YAML expands shell `${...}` expressions.

5. **Check and run manually.** These direct official commands use `--profile-file`, independent of named-profile search directories:

```sh
tunnel-client doctor --profile-file "${ROUNDTABLE_HOME}/data/tunnel/roundtable.yaml" --health.listen-addr 127.0.0.1:0 --explain
tunnel-client run --profile-file "${ROUNDTABLE_HOME}/data/tunnel/roundtable.yaml" --health.listen-addr 127.0.0.1:0 --health.url-file "${ROUNDTABLE_HOME}/data/tunnel/health.url" --pid.file "${ROUNDTABLE_HOME}/data/tunnel/tunnel.pid" --log.file "${ROUNDTABLE_HOME}/data/tunnel/runtime.log" --log.http-raw-unsafe=false
```

When an existing HTTP CONNECT proxy is required, append `--control-plane.http-proxy env:ROUNDTABLE_OUTBOUND_PROXY` to **both doctor and run**; set that environment variable to `http://127.0.0.1:<PORT>`. This is the Tunnel client's own option: the project's proxy variable does not configure it automatically. Do not use global `--http-proxy` to route local MCP through a proxy. Remove inherited `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` and lowercase equivalents from this launch environment so the control plane uses its explicit proxy and loopback MCP stays direct, without changing system or Clash settings.

The official `--profile <name>` alternative requires a file in the client's profile directory or an explicit `--profile-dir`. `scripts/start-local.sh tunnel` accepts `ROUNDTABLE_TUNNEL_PROFILE_FILE` for a file, or `ROUNDTABLE_TUNNEL_PROFILE` for the named route; do not pass a file path as a profile name. Explicit `--log.file stdout` created a file literally named `stdout` in the tested 0.0.19 setup, so these commands use a private absolute log path instead of relying on that string to mean standard output. Keep raw HTTP logging off; do not publish entire health details or logs, which may contain local paths and request information.

Interpret doctor in layers: profile parsing, key references, and loopback reachability do not prove cloud connectivity. With fixed Bearer/No authentication, 0.0.19 doctor may report an isolated missing `oauth_metadata` failure; do not disable authentication or fabricate metadata. Confirm authenticated local MCP initialize succeeds, then verify runtime health `ready`, control-plane polling/last_success, proxy routes, and OAuth `not_advertised`. Only consistent evidence justifies classifying this as an unused OAuth discovery check; fix other failures. Runtime readiness still does not establish native tool calls.

6. **Create and connect the ChatGPT plugin.** In the intended account/workspace, choose “Add custom MCP server” from the plugin page (labels may vary), name it, select **Tunnel** as Connection, select/enter the same Tunnel, and choose **No authentication**. Finish both creation and connection. Backend authentication remains enabled. Expose only the authorized test room's dot identity; do not install duplicate plugins.
7. **Refresh and verify.** Use “Refresh tools” on the existing plugin's management page, particularly after enabling gateway Events. Rediscover tools in the real Dot conversation and call `list_rooms` and `list_bots` to check the unique room and intended member. Separately verify `initialize.capabilities.events`, `events/list`, and the product's event sources/schema; tool presence does not prove event discovery. The product may require refreshing the current conversation; visibility in another thread is not visibility here.

## First-time Events discovery limitation and subscription confirmation

**Safe first-time discovery:** this version accepts an empty callback allowlist with Events enabled. It advertises Events but rejects every subscribe before DNS/challenge/persistence. Obtain the actual hostname from a platform-generated request and the safe rejection log, independently verify its source, explicitly approve it and restart only the managed gateway. Never guess a hostname or disable validation. See [managed bootstrap](SETUP_AUTOMATION.en.md).

Once Events is running with a trusted exact allowlist:

1. Refresh plugin discovery and confirm `handoff.available` takes `{}`. Let the product generate the actual callback URL and signing secret; never fabricate them manually.
2. Explicitly request a subscription for this member. Use an event trigger without a separate polling schedule. If the real request is rejected, inspect only `callback_host_not_approved host=…` in safe logs and verify the hostname belongs to the intended platform interaction; a log entry or plausible domain alone does not establish trust. Once verified within the authorized scope, approve that exact host, restart only the affected MCP gateway with no parallel tasks, preserve the private Events DB, and retry. An observed hostname is not a permanent universal value for all accounts.
3. On creation errors/timeouts, first check whether the platform already created an automation/subscription, then inspect gateway subscription state. Do not duplicate an uncertain creation. Distinguish platform pre-creation connector validation failures, callback host rejection, and challenge failures. Without access logging, missing log entries do not prove the request never arrived.
4. Create one read-only roundtrip only after confirming a valid successful subscription. Receiving an event is not execution success: correlate the claim and report with the same task. See [roundtrip acceptance](ROUNDTRIP.en.md).

## Uptime, expiry, and recovery

The installation maintainer reports, via Grok, observing terminal routine receipts and automatic subscription renewal before expiry in one real installation. This documentation update did not independently reproduce that report; each deployment must verify its own task/receipt correlation, subscription records and refresh time. See [evidence limits](../VERIFICATION.md#maintainer-reported-acceptance).

The local server, MCP gateway, Tunnel process, and required proxy must remain available. Sleep, network loss, and manual process exits interrupt the route. Retain non-secret PIDs/health addresses and verify ownership before stopping a process; a gateway-only change should not stop the server. Manual startup does not configure boot-time operation. The launchd templates below require separate path rendering, secret injection, and explicit loading; these commands do not load them.

The Platform key has its own expiry. Renew securely with the same minimal scopes and restart only the Tunnel that needs the updated environment. Events subscriptions default to, and are capped at, one hour. The operator must verify the chosen product renews them and observe expiry; this repository has no universal client subscription-renewal controller. New subscriptions start at the current event boundary with no historical replay. Do not hide outages by deleting databases, recreating tasks, or resetting allowances. Recheck original task state, subscription expiry, and health after recovery. Preserve and protect the Events DB because it contains callback signing secrets.

## Lease and callback operations

`claim_assignment(..., lease_seconds=60)` accepts integer 30–1800 seconds; expiry and progress renewal are capped by the task deadline. Progress renews the selected duration. Task `timeout_seconds` accepts 30–86400. Expired work can be reclaimed within attempt/budget limits; an old lease cannot report after reclaim. External Codex effects are not automatically undone or replayed.

Events remain off unless explicitly configured and subscribed. `ROUNDTABLE_EVENT_TIMEOUT` sets the total callback deadline (default 20 seconds, 0.01–120), including DNS and transport. Ambient proxy environment variables fail closed without an explicit setting. To explicitly use a trusted HTTP CONNECT proxy set `ROUNDTABLE_OUTBOUND_PROXY` (or legacy `ROUNDTABLE_EVENT_PROXY`) to its HTTP origin; credentials are unsupported. In direct mode callback DNS results must all be public and the selected IP is pinned. In explicit proxy mode CONNECT targets the canonical hostname; only the trusted proxy resolves it, while TLS/Host retain that hostname. No redirect or direct fallback occurs. Uninterruptible DNS retains a bounded worker slot until it finishes. Rejected hosts log only `callback_host_not_approved` and a sanitized hostname.

After separate subscription approval, `handoff.available` means: receive_assignments → claim_assignment → dot checks task/user authority and may create a Codex task using its own connected-computer tools → report progress → completed/failed. An event is a wake hint, not authorization. Never execute instructions embedded in task data outside the approved task scope.

To opt in to the Events endpoint after configuration approval, start the gateway with:

```sh
sh scripts/start-local.sh mcp --events-db "${ROUNDTABLE_HOME}/data/events.db" --event-host approved.hostname
```

This shorthand assumes the secret manager has injected grants/Bearer into the **current launch environment**. The earlier hidden-input launcher does not retain secrets in its parent shell. For interactive hidden input, gracefully stop your managed old MCP (not the server), then reuse this complete launcher, replacing `<EXACT_APPROVED_CALLBACK_HOST>` with the actual verified approved hostname:

```sh
.venv/bin/python -c 'import getpass, json, os, warnings; warnings.simplefilter("error", getpass.GetPassWarning); token = getpass.getpass("Dot member token (hidden): "); os.environ["ROUNDTABLE_HTTP_GRANTS"] = json.dumps([{"room": os.environ["ROUNDTABLE_ROOM"], "agent": os.environ["ROUNDTABLE_AGENT"], "token": token}]); os.environ["ROUNDTABLE_TUNNEL_AUTH_HEADER"] = "Bearer " + token; os.execvp("sh", ["sh", "scripts/start-local.sh", "mcp", "--events-db", os.path.join(os.environ["ROUNDTABLE_HOME"], "data/events.db"), "--event-host", "<EXACT_APPROVED_CALLBACK_HOST>"])'
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
| `ROUNDTABLE_TUNNEL_PROFILE_FILE` / `ROUNDTABLE_TUNNEL_PROFILE` | Reviewed file path or local profile name for `start-local.sh tunnel` |
| `ROUNDTABLE_EVIDENCE` | Local client's default roundtrip evidence path; defaults to `data/roundtrip.json`, overridden by `--evidence` |
| `ROUNDTABLE_TERMINAL_NOTIFICATIONS` | Only `1` enables the server terminal worker; disabled by default |
| `ROUNDTABLE_TERMINAL_ROOM` / `ROUNDTABLE_TERMINAL_ORIGIN` | Room and current origin member covered by the terminal worker |
| `ROUNDTABLE_TERMINAL_LEDGER` | Shared durable ledger for manual and automatic receipts; default `data/terminal-receipts.db` |
| `GROK_ROUTINE_URL` / `GROK_ROUTINE_KEY` / `GROK_ALLOWED_HOST` | Authorized routine HTTPS URL, secret, and exact hostname allowlist; see [terminal receipts](TERMINAL_RECEIPTS.en.md) |

Events database and approved hosts are CLI arguments, `--events-db` / `--event-host`, not environment variables. Declare a nondefault external HTTPS URL with `--public-url`; the listener remains loopback-only.

The launchd templates contain only `ROUNDTABLE_HOME`; they do not inherit terminal `export` statements. Render paths locally and configure the required environment separately for each service. When proxying is required, add `ROUNDTABLE_OUTBOUND_PROXY` to both server and MCP environments. Templates default to `RunAtLoad=false` and `KeepAlive=false`; they do not load themselves or enable Events, and this documentation does not require loading them. Never commit real secrets or rendered deployment configuration.

## One-time user acceptance checklist

The user performs these steps with their own accounts and authorized environment. Replace placeholders and retain the original task and ledger; do not hide uncertain outcomes by deleting a ledger or recreating a task.

1. **Check existing instances:** use dedicated ports/databases on first setup. For an existing installation, verify ownership and back up data. Stop the specific managed process in a maintenance window only when updating its configuration; never share a database between instances or unnecessarily restart a healthy server.
2. **Choose outbound mode and start processes:** only when a proxy is required, configure `ROUNDTABLE_OUTBOUND_PROXY=http://127.0.0.1:<PORT>` separately in server/routine and MCP gateway environments. Direct installations leave the explicit proxy unset and avoid unintended ambient proxy settings. A running process does not see later terminal exports; restart the affected process in your own maintenance window when configuration changes.
3. **Doctor:** run `.venv/bin/python scripts/check.py doctor` with the member environment. Confirm both `outbound_local` and `outbound_backend` report `configured=true`; their `mode` should be `trusted_proxy_dns` for explicit-proxy installations or `direct_public_ip_pinning` for direct installations. `outbound_backend` is a structured object. This does not prove vendor callback reachability or validate the separate gateway environment.
4. **Tool discovery:** complete the authorized private Tunnel setup and select **No authentication** in the ChatGPT connector. Discover tools in the real Dot conversation and call `list_rooms` / `list_bots` to verify the unique expected room/member. Tunnel doctor success alone is insufficient.
5. **Approve the callback hostname:** inspect the actual product-provided hostname and configure the gateway's exact `--event-host` and private `--events-db` as above. Do not use wildcards or disable host checks. Restart only your managed gateway if needed.
6. **Allowance:** from the administrator environment, run `.venv/bin/python scripts/admin.py allowance '<ROOM_ID>' '<ORIGIN_AGENT_ID>' 1` within the authorized scope. Never put administrator credentials in bot configuration.
7. **Subscribe to `handoff.available`:** explicitly ask Dot to listen for this member's work and confirm subscription success. Subscriptions expire and are not permanent authorization; events are wake hints only.
8. **Native roundtrip:** with the origin member's environment, run `roundtrip --worker '<WORKER_AGENT_ID>'` from the [roundtrip guide](ROUNDTRIP.en.md). Observe real Dot waking, claiming, and returning the nonce, and the origin retrieving the same task's result. Re-read with `doctor --evidence`; record protocol correlation, native conversation, and wake observations separately. This read-only roundtrip creates no Codex task and sends no Grok routine.

If a step fails, record its stage and safe error code, then resume from the original task state after fixing the issue. Real work handoffs and optional Grok terminal receipts need their own explicit scope; this checklist does not replace that authorization or acceptance.

## Troubleshooting, backup, and access removal

| Symptom | Next action |
|---|---|
| Port occupied | Inspect listener/process ownership; reuse a healthy instance or stop your old managed instance in a maintenance window, never an unknown process. Update client URL, gateway, and profile together if changing ports |
| `field server_url not found` | Update the local profile to the template's `server_urls` list |
| `tunnel_authorization_mismatch` | Check matching full scoped Bearer in gateway/Tunnel, ChatGPT No authentication, and forwarded Authorization overrides; never print values or disable auth |
| Local target reachable, control plane failing | Check key expiry/Read+Use, organization/workspace, explicit control-plane proxy, and runtime health; do not substitute a model key or change Clash |
| Tools present, event source missing | Verify gateway Events advertisement, use the existing plugin's Refresh tools, then refresh current conversation source/schema discovery; do not duplicate the plugin |
| Subscription creation fails | First check for an existing subscription, then distinguish platform validation, exact-host rejection, and challenge failures. Stop without a real host; never guess a URL |
| No event after computer recovery | Check all three processes, proxy, key, subscription expiry, and original task state. New subscriptions do not guarantee replay of earlier events |

Back up task/Events databases, necessary configuration, and secret-manager recovery material using encrypted, operator-only offline/controlled storage, never GitHub, chat, or public artifacts. Do not copy only a live SQLite `.db` while ignoring its WAL: use a consistent SQLite online backup procedure or gracefully stop its writers during planned maintenance before copying. Avoid simultaneous processes sharing a database during restore and preserve original tasks and uncertain-send ledgers.

To remove this integration, first cancel its product event automation/subscription and confirm renewal stops, then disconnect/uninstall the target ChatGPT plugin. Verify ownership before stopping its dedicated Tunnel/MCP processes. Revoke only its dedicated runtime key and target Tunnel/workspace access, without affecting shared resources used by other applications. To revoke local member access too, remove that member through the administrator UI and update gateway grants; merely stopping the Tunnel does not revoke a leaked member token. Keep protected backups; decide permanent data deletion separately. Do not delete all of `data/`, global keys, or the organization. Leave a shared server running for other members.

Managed `up` defaults to temporary macOS sleep assertions tied to this server instance, with `--no-caffeinate` opt-out and verified process status. Manual `start-local.sh` is unchanged. Read the [AC/lid/network limitations](SETUP_AUTOMATION.en.md); no persistent power setting is changed.
