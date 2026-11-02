# Managed local setup

These scripts automate local identities, private files and process lifecycle. They do **not** create vendor accounts, install Tunnel, subscribe to Events, grant a bot computer permissions, or load launchd. Linux/macOS with Python 3.12/3.13 are supported; Windows process management is not implemented. Use a dedicated checkout. Do not point these scripts at an existing manually managed database without an explicitly reviewed manual state transfer.

For persistent administrator credentials, room.env, safe UI access, create/tasks/inbox, explicit startup diagnostics, and manual state-transfer guidance, follow [runtime onboarding](ONBOARDING_RUNTIME.en.md). Windows credential persistence is separate from unsupported Windows process management.

## 1. Prerequisites and manual account checklist

<a id="tunnel-client-install"></a>

- Create a virtual environment and install `requirements.lock` as in README. Review source before running it. Install the compatible official [Tunnel client](https://github.com/openai/tunnel-client/releases) yourself; flags/schema below target **0.0.19**. Check the installed version before replacing anything.

<a id="platform-tunnel-runtime-key"></a>

- In [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels), confirm the account, organization and actual ChatGPT workspace. Reuse the intended Tunnel or create one deliberately; matching email is not workspace binding.
- In [Platform keys](https://platform.openai.com/settings/organization/api-keys), create **Restricted**, **Tunnels Read + Use only**. Do not grant Manage or model permissions. Choose the expiry deliberately; **Never may be available and seven days is not a project requirement/default**. Record renewal responsibility. If the exact permissions are unavailable, stop instead of using an unrestricted project key. The save script validates syntax, not scopes or expiry.

<a id="chatgpt-connector"></a>

- ChatGPT must support the private Tunnel connection and Events in the intended workspace. Select **Connection: Tunnel**, the correct Tunnel, and **No authentication** for this fixed local identity; refresh the existing connector's tools/Events metadata after configuration changes. The Tunnel injects a complete Bearer value. It does not turn off gateway authentication. [Official header precedence](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md): forwarded Authorization overrides local headers case-insensitively. `tunnel_authorization_mismatch` means fix that configuration, never remove auth.

<a id="grok-local-permission"></a>

- Grok needs its own authorized local tool/computer access and scoped member environment. Roundtable cannot install that permission or run Codex for it. A routine is optional and requires explicit approval; see [official routine guidance](https://cursor.com/help/grok-bot/routines) and [current usage/pricing](https://x.ai/bot). Do not assume a fixed per-callback price or that HTTP 200 means completed work.
- If the machine needs a proxy (including Clash fake-ip), retain its existing configuration. Use the explicit proxy option below; do not change global networking or force direct access.

## 2. Initialize one instance

```sh
export ROUNDTABLE_HOME='<CHECKOUT_DIRECTORY>'
cd "${ROUNDTABLE_HOME}"
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python scripts/setup-local.py --origin grok --worker dot --allowance 20 \
  --server-port '<SERVER_PORT>' --mcp-port '<MCP_PORT>'
```

The default state directory is outside the checkout and platform-specific, mode 0700; see [locations and migration](STORAGE.en.md). Use `--name <INSTANCE_NAME>` consistently for a named instance. Omit port flags to select distinct available loopback ports; explicit port flags take precedence. Initialization creates a private administrator secret, registers both bots through a temporary loopback server on an OS-assigned port, creates one room and independent `grok.env`/`dot.env` files (0600), and closes that temporary server. The origin allowance defaults to 20; use `--allowance 1` for minimal acceptance testing. The worker allowance remains zero: receiving, claiming and reporting do not need initiation allowance. No external request is made.

Re-running setup verifies the completed instance and skips creation without overwriting credentials. It does not change existing ports, names or allowances. An interrupted setup refuses automatic recreation, preserving its private recovery files: inspect/recover offline, or deliberately choose a new empty instance directory with `--state-dir '<PRIVATE_INSTANCE_DIRECTORY>'`. Do not delete an active instance to resolve a configuration error. Every later command must use the same `--state-dir` when customized. Do not share one database across instances.

Generated `.env` files are data, never shell programs; the scripts parse them without `source`. They contain real secrets: do not `cat`, copy into chat, upload, or commit them. `data/` is gitignored. Each vendor's approved local tool should receive only its own member environment via secure local injection, never `admin.json`/`admin.env` or the other member's file. Existing manual integrations can continue using `start-local.sh`; do not mix their process ownership with this manager.

## 3. Profile, hidden runtime key, and startup

Edit only the non-secret Tunnel ID in `<STATE_DIRECTORY>/tunnel.yaml`; setup copied the official `server_urls` list with `channel: main` and the chosen MCP port. Do not replace it with obsolete singular `server_url`. Keep the `api_key` and `Authorization` fields pointing at the environment-variable references from the template; never paste real values. The manager injects the full credential only into the gateway and Tunnel child environments.

```sh
sh scripts/save-runtime-key.sh
# Hidden terminal input; saves runtime-key.env as 0600, without echo.
# Existing nonempty files are refused; deliberate rotation uses --replace.
sh scripts/up.sh --without-tunnel
.venv/bin/python scripts/local_runtime.py doctor
sh scripts/up.sh
```

`up` starts server → MCP → Tunnel, reuses only this instance's verified processes, and refuses occupied ports/foreign PIDs. Missing profile/key causes a safe failure; components started by that invocation are rolled back. Run from an interactive terminal for secret input; hidden input fails closed if echo suppression is unavailable. A syntax-valid key is not proof of its actual Platform rights.

<a id="outbound-proxy"></a>

For a network that requires a proxy, use it on the **first** startup:

```sh
sh scripts/up.sh --without-tunnel --proxy 'http://127.0.0.1:<PORT>'
# After completing the profile/key:
sh scripts/up.sh
```

The explicit proxy is saved in this instance. The manager clears ambient HTTP_PROXY/HTTPS_PROXY/ALL_PROXY and lowercase equivalents only in child environments. Events/Grok receive `ROUNDTABLE_OUTBOUND_PROXY`; Tunnel receives `--control-plane.http-proxy`. Local MCP remains direct loopback. A running instance refuses a proxy change; stop only this instance before changing it. An explicitly selected proxy is a trusted DNS/routing boundary; direct mode retains public-IP validation. No global proxy settings are changed.

Tunnel uses `--profile-file`, private health URL/PID files and a private FIFO log destination; the supervisor writes filtered status records to `tunnel.log`. Other components use `server.log`/`mcp.log`. These are 0600, not literal `stdout` files. Unknown vendor text is discarded rather than persisted; no raw HTTP/body logging. These deliberately minimal logs may require official platform diagnostics to explain a cloud-side error. Do not publish entire private state directories.

<a id="callback-approval"></a>

## 4. Connect and bootstrap Events safely

1. Finish the ChatGPT Tunnel/No authentication configuration. Refresh the **existing** connector's tools/Events metadata. Verify native `list_rooms` and `list_bots` show only the expected room/identity. Local readiness does not establish this.
2. The managed MCP advertises Events with **zero approved callback hosts** initially. `events/list` works; all subscriptions are rejected before DNS, challenge or persistence. An example hostname is never approval.
3. Ask the platform to subscribe once to `handoff.available` with `{}`; use [the prompt](PROMPTS.en.md). The platform generates the callback URL/signing secret. If rejected, inspect only `callback_host_not_approved host=…` in `mcp.log`. Independently confirm that hostname belongs to this authorized platform request. Do not guess, use a wildcard, or paste a callback URL/key into commands.
4. Explicitly approve the verified exact hostname, then restart **only this managed MCP** in a quiet window. The server and Tunnel remain running; tools briefly disconnect:

```sh
.venv/bin/python scripts/local_runtime.py approve-host --host '<VERIFIED_CALLBACK_HOST>'
sh scripts/down.sh --component mcp
sh scripts/up.sh --component mcp
```

5. Refresh metadata if needed, inspect whether the first platform create succeeded or failed, and retry only if absent. Never blindly create duplicates after a timeout. Confirm a real active subscription and its refresh time with `doctor` and the platform task view. A successful task toggle does not guarantee a new subscribe call.

`connectors.api.openai.com` was observed for one real installation; it is **not** a permanent universal hostname. The example env is informational and not read as approval. A remaining platform limitation is possible: if it never sends a real subscribe or cannot expose Events, this repository cannot invent its callback or fix the account/workspace entitlement.

<a id="dot-automation"></a>

The installation maintainer reports that one real installation received Grok terminal routine receipts and automatically renewed subscriptions before expiry. This report was relayed through Grok, not independently reproduced in this documentation update; each deployment must verify receipt/task correlation and renewal timestamps. See [evidence limits](../VERIFICATION.md#maintainer-reported-acceptance).

Subscriptions default to one hour and are capped at one hour. Platform renewal is **not guaranteed**; verify the earliest `refreshBefore` and actual renewals. Backend connection/5xx failures preserve existing subscriptions with `backend_unavailable` and bounded backoff; 401/403 revoke them. Invalid 200 bodies never authorize. Expiry/cancellation still remove state, and recovery does not replay already acknowledged events.

If the platform automation/subscription is lost, inspect existing records first. Toggle the existing automation only when appropriate, or recreate only after confirming it is absent; then verify actual subscribe and renewal records and the new refresh time. A toggle is not proof of renewal, and a new subscription does not replay missed work.

## 5. Doctor and layered acceptance

```sh
sh scripts/status.sh
.venv/bin/python scripts/local_runtime.py doctor
.venv/bin/python scripts/local_runtime.py client --operation probe
# Only after the receiver/subscription is ready and the user authorizes one test:
.venv/bin/python scripts/local_runtime.py client --operation roundtrip --timeout 600
```

The local owner doctor reports component running/readiness, Events enabled/approved-host count, this worker's active subscription count/earliest refresh time, Tunnel readyz, origin allowance/low warning, ambient proxy presence, and scoped roundtrip evidence. It never exposes callback URLs or keys. It is a filesystem-owner command, **not an MCP member tool**. The existing member `local_client.py doctor` remains scoped to HTTP and its evidence file; it cannot read an administrator DB.

Roundtrip consumes one origin budget unit and creates one read-only nonce task; wait and task deadline use the requested timeout (integer 30–86400). Evidence remains in `<STATE_DIRECTORY>/roundtrip.json`. Do not edit it to claim success. Configuration → HTTP transport → native tool call → manually requested nonce → webhook-triggered nonce are distinct evidence levels. Actual native tools/manual nonce/webhook-triggered claim-and-report have been observed in one installation; **Codex execution and Grok terminal routine acceptance were not established by that test**. Synthetic tests prove neither native identity nor wake. See [roundtrip evidence](ROUNDTRIP.en.md).

For an inherited member environment, `local_client.py task <TASK_ID>` and `context <TASK_ID> --body '<CONTEXT>'` do not wait for stdin. JSON stdin remains supported without positional task ID, with a two-second input deadline. Conflicting inputs are rejected.

## 6. Optional Grok receipt, upkeep and removal

<a id="grok-routine"></a>

After explicitly approving a real routine, run `sh scripts/set-grok-routine.sh` and enter its HTTPS URL/key using hidden prompts. The exact allowed hostname is derived and validated. The private opt-in file enables the terminal worker on the **next server start**; this command does not restart anything. Merely copying a sample env never enables delivery. Keep the terminal ledger across restarts: one reserved attempt per task, no automatic uncertain retry. See [receipt semantics](TERMINAL_RECEIPTS.en.md).

```sh
sh scripts/down.sh              # this instance's Tunnel → MCP → caffeinate → server
sh scripts/up.sh                # restart only in an approved maintenance window
sh scripts/render-launchd.sh --output '<REVIEW_DIRECTORY>'
```

Rendered plists contain no secret values, correctly escape paths, use single-component startup, and have RunAtLoad/KeepAlive false. They are **not loaded**. Review lifecycle ordering, secret-file access and your user's launchd policy before separately authorizing installation; loading is not part of setup.

Keep the Mac and its existing proxy available; sleep/network loss interrupts delivery. These scripts do not change persistent power settings; managed `up` uses caffeinate during its runtime. On recovery inspect original tasks, health, key expiry, lease ownership and actual subscription renewal before creating anything new. A failed task is not automatically safe to repeat. If stop returns ownership mismatch or cleanup unconfirmed, preserve records and inspect that specific instance; never kill an unrelated PID or remove the safety record to force restart.

For backup, stop only this instance or use a consistent SQLite backup, protect the backup like credentials, retain Events and terminal ledgers, and never upload `data/`. To remove access: pause/delete the platform automation, revoke the connector and its scoped membership, revoke the dedicated runtime key/Tunnel binding if no longer used, stop this instance, and remove only its reviewed launchd entries if separately installed. Do not delete shared vendor resources or erase ledgers to retry uncertain sends. Delete private local files only after deciding retention and revocation; deleting a file alone does not revoke a copied credential.

When ambient proxy variables exist without an explicit instance proxy, `up` fails with `explicit_outbound_proxy_required`; `doctor` remains available and reports their presence. Configure the intended proxy explicitly, or deliberately clear those variables only for this command when direct access is intended.

<a id="sleep-prevention"></a>

## macOS sleep prevention (temporary, instance-owned)

On macOS, a normal managed `up` that includes the server also starts this instance's own `caffeinate -i -s -w <SERVER_SUPERVISOR_PID>`. The target is the verified server supervisor: it exits after its actual server process group is cleaned, so the assertion follows the server lifecycle. This does not alter persistent power settings. To opt out, use `sh scripts/up.sh --no-caffeinate` (or add it to your `--without-tunnel` invocation). It stops only this instance's existing managed caffeinate, if any. Single-component MCP/Tunnel restarts do not change this choice. A later full `up` defaults to enabling it again unless the flag is supplied.

The local macOS `man caffeinate` documents `-i` as preventing idle system sleep, `-s` as preventing system sleep **only on AC power**, and `-w` as releasing the assertion when the target PID exits. No `-d` or `-u` is used: keeping the display awake is not requested. Locking the screen or turning off the display usually differs from system sleep; closing the lid, forced sleep, power loss and network loss are **not** guarantees of continued connectivity. Do not claim “never disconnects.” You may choose your own power settings separately; setup runs no `sudo pmset` and changes no persistent system settings.

Non-macOS platforms and machines without the binary receive an explicit skipped status. `down` stops only the managed caffeinate with verified instance/PID ownership, including before stopping the server. Server startup failure cannot start it; server exit releases `-w`, and the supervisor reaps the owned child group. `status`/owner `doctor` report actual process-running and server-binding checks, enabled/support state and the AC-only restriction. `os_assertion_verified:false` is deliberate: process inspection does not independently query power-management assertions or promise that the hardware will stay awake. Do not kill unrelated caffeinate processes.

Development tests use a **fake caffeinate executable only**. They verify argv, owned lifecycle, server exit, opt-out, unsupported/missing binaries and foreign-PID refusal; no real sleep assertion or power-setting change is part of those tests. Rendered server launchd entries call the same `up --component server` default; review or add `--no-caffeinate` before separately authorizing loading. No plist is loaded by the renderer.

Optional persistent power choices are separate operator actions, not the default recommendation. `man pmset` documents `-c` as AC/charger-only and requires administrator privileges for modifications. Persistent changes can affect all applications and continue after Roundtable stops, increasing power use and heat. Before any separately approved change, record the original AC values for each setting; restore those same values afterward, rather than resetting unrelated settings. This guide provides no mutation command and the scripts never apply pmset settings.

Logs are in the separate [log directory](STORAGE.en.md), rotated at 10 MiB with three backups by default. Plists use a shell wrapper rather than a fixed venv interpreter; recreating the venv at the same path does not require re-rendering.

Unconfigured `up`, `down`, `ui` and `client` return `not_configured_run_setup` with a complete setup command, without creating a partial instance. Invalid names, relative XDG_STATE_HOME and missing LOCALAPPDATA report specific safe path reason codes and `StatePathError`; raw environment values are not echoed.
