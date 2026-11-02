# Runtime onboarding and credential recovery

Use this with the [managed setup guide](SETUP_AUTOMATION.en.md). Account configuration, exact callback approval, subscription renewal, and provider permissions remain manual. This page describes product capabilities, not permission to migrate or rotate an existing installation.

## Initialize and open the UI

Run commands from `${ROUNDTABLE_HOME}` with its installed `.venv`. Use the same `--state-dir '<PRIVATE_INSTANCE_DIRECTORY>'` on every command when overriding the [platform default state directory](STORAGE.en.md).

```sh
.venv/bin/python scripts/setup-local.py --origin grok --worker dot --allowance 1 \
  --server-port '<SERVER_PORT>' --mcp-port '<MCP_PORT>'
sh scripts/up.sh --without-tunnel
.venv/bin/python scripts/local_runtime.py ui
```

Setup persists administrator, room-owner (`room.env`) and separate member credentials with private permissions. Repeated setup never replaces them. Do not give room-owner credentials to bots. On macOS/Linux, `ui` requires this manager's healthy server and opens a one-time login link using `open`/`xdg-open`. An authenticated administrator request issues a random 60-second code; its URL fragment is cleared before exchange. Codes are single-use, bounded and rate-limited. Exchange requires the actual IPv4 loopback peer, exact Host and same-origin Origin. The resulting one-hour, nonrenewable session permits room/task operations, not credential, membership or login-code administration. It is session-storage-only, even if manually pasted. The long-lived administrator token never enters the link, output or launcher arguments. Short-lived codes are still secrets: browser/OS URL records may briefly retain them; do not share links. Restart invalidates these in-memory codes and sessions.

For deliberate clipboard access, use `.venv/bin/python scripts/local_runtime.py ui --copy-token`: macOS uses `pbcopy`, Linux prefers `wl-copy` then `xclip`, Windows uses `clip.exe`. The token is supplied through stdin, never printed. Without a helper, the command reports the private credential-record location, not its contents; use a trusted local credential manager. Windows managed auto-login/process supervision is unsupported. Clipboard managers and sync can retain copied tokens: clear them afterwards. Setup never copies credentials.

**Which path is remembered:** opening the local address directly only shows **Connect**. A temporary session obtained through `ui` cannot use **Remember on this device** (the checkbox is disabled); after closing the tab, the one-hour expiry or a server restart, run `ui` again. To reconnect automatically across browser restarts, copy the long-lived administrator token with `ui --copy-token`, paste it under **Connect**, tick **Remember on this device**, then clear the clipboard.

Then edit the non-secret Tunnel ID in the generated profile, run `sh scripts/save-runtime-key.sh`, `sh scripts/up.sh`, and `.venv/bin/python scripts/local_runtime.py doctor`. Hidden key input requires a terminal. A complete `up` checks `runtime_key_missing`, `tunnel_client_not_found`, and `tunnel_id_placeholder` before starting components. `--without-tunnel` deliberately skips those Tunnel checks. Unexpected failures show only a category and exception class, never the exception message. A syntax check does not prove runtime-key permissions or expiry.

## Persistent administrator credentials

Standalone `server.py` now creates and reuses a private credential beside its database in `admin-credentials/admin.json` (the default database is `<STATE_DIRECTORY>/manual/roundtable.db`, separate from managed state); `--admin-state '<PRIVATE_DIRECTORY>'` chooses a different location. Managed instances keep it in their state directory. Do not generate a new environment token on every launch. An explicitly supplied `ROUNDTABLE_ADMIN_TOKEN` overrides the stored value for that process only and never changes it. Doctor reports `admin_environment_override_active` without displaying the value.

By default, credentials are stored in a POSIX 0700 directory / 0600 file. Windows administrator credential persistence uses a current-user-only ACL, checks it before writing, and refuses unsafe/unavailable ACL protection; Windows managed process supervision remains unsupported. Optional `--keyring` on setup or `--admin-keyring` on standalone server prefers an installed supported OS backend (macOS Keychain, Linux Secret Service, Windows Credential Manager). Install and configure the optional `keyring` package yourself if desired; see its [official documentation](https://keyring.readthedocs.io/en/latest/). Unknown/plaintext backends are not trusted. If no supported backend is available for initial creation, private-file storage is used. An existing keyring identity that becomes inaccessible fails closed rather than silently creating another credential. A keyring write error also fails closed. Keyring metadata is bound to the state path. Keep that path or arrange an explicitly reviewed OS credential transfer with your administrator; copying metadata alone is not a supported credential transfer. Standalone servers can retain their original --admin-state path.

Stop only the instance you intend to rotate, unset any environment override, then use:

```sh
.venv/bin/python scripts/local_runtime.py rotate-admin-token
# Standalone alternative, after stopping that standalone server:
.venv/bin/python admin_credentials.py rotate-admin-token --state-dir '<ADMIN_STATE_DIRECTORY>'
```

Rotation never prints the new token. Restart that instance to adopt it and use `ui` to reconnect on macOS. Existing room/member tokens are unchanged; remove old browser access separately. Keep private backups offline, never in Git or chat. After safely publishing the new credential record, rotation deletes the old keyring entry. If deletion fails, `old_keyring_entry=failed_manual_cleanup_required` reports that the new credential is committed but old-entry cleanup needs your OS credential manager; it does not roll back or print the secret. Revoking an environment override requires updating its external secret source too.

## Browser storage and task visibility

Only on the exact `127.0.0.1` origin, access tokens default to `sessionStorage`: reloads in the same tab reconnect and select the last room still accessible. **Remember on this device** is off initially; opting in uses `localStorage` across browser restarts and automatically reconnects to the last accessible room. Unchecking removes the persistent copy and uses session storage. **Forget saved access** clears memory and both stores, clears password fields, and invalidates pending authentication responses. It attempts to revoke a temporary UI session; if that request fails or the page closes first, the session can remain valid until expiry or server restart; it does not revoke long-lived administrator or member credentials. Invalid restored credentials are discarded. If browser storage is blocked, connection remains memory-only. Other hostnames do not persist tokens.

Storage is scoped to the browser origin, including port, but is not a vault: same-origin scripts, extensions, browser-profile backups, or another person using the profile may access it. Session restore/duplicated tabs may preserve session storage; use Forget when finished. Use a private trusted browser profile and avoid persistent storage on shared devices.

Grok and Dot cooperate through task handoffs, so an empty discussion is normal. A room with tasks but no discussion messages initially opens **Tasks & handoffs**; once any discussion message exists, **Discussion** opens first and you switch manually. Selecting Discussion stays selected during polling. Task lifecycle details remain in the existing task view; no duplicate system messages containing leases or tokens are generated.

## Grok creates a task without sourcing credentials

The managed client loads only the origin member file. It does not use the admin or room-owner token. Replace the worker ID if setup used a different one; the bot still needs its own authorized local execution permission.

```sh
.venv/bin/python scripts/local_runtime.py client --operation create <<'JSON'
{"title":"Read-only check","context":"Use only authorized project context.","assignments":[{"worker":"dot","instruction":"Report current project status without making changes."}],"budget":1,"timeout_seconds":600,"request_id":"read-only-check-001"}
JSON
.venv/bin/python scripts/local_runtime.py client --operation tasks
.venv/bin/python scripts/local_runtime.py client --operation inbox
```

Creation requires JSON stdin (32 KiB maximum, two-second total read deadline); a terminal or stalled pipe fails rather than waiting forever. `create`, `tasks`, and `inbox` reject `--task-id`/`--body`. `inbox` is the origin's inbox, not another member's. A repeated identical request ID uses the existing task; choose a fresh ID only for intentionally new work. Task content does not expand permissions. An accepted task is not evidence of a provider waking or completing it.

## Manual state transfer and pending routine approval

There are no automatic legacy-import or state-migration commands. Follow the [manual storage checklist](STORAGE.en.md): stop, checkpoint, privately copy, verify and retain the original. Heterogeneous old layouts need operator review, not automatic guessing or credential replacement.

A deliberately prepared private `routine.pending.json` can be approved while the instance is stopped with `.venv/bin/python scripts/local_runtime.py approve-routine`. It must contain an `environment` object with exactly `GROK_ROUTINE_URL`, `GROK_ROUTINE_KEY` and `GROK_ALLOWED_HOST`. Review the endpoint and authority privately first; never paste secrets into commands or chat. The command validates HTTPS and the exact host, refuses an existing active routine, and writes explicit approval without sending a request. The next `up` may enable terminal receipts, so retain the existing receipt ledger and resolve old uncertain delivery history before cutover. Alternatively use the hidden-input `set-grok-routine.sh` for newly approved configuration.

Rendered launchd plists include Homebrew and standard system paths and contain no credential values. Rendering never loads jobs. The rendering directory must be private; permissions are not silently widened. Native OS keyrings and Windows ACL behavior require platform-specific acceptance; synthetic tests are not a claim of real-provider or cross-platform end-to-end success.

## Repair a missing room credential file

Repeated setup and `repair-room-env` first recover `room.env` from a matching private recovery record. A database hash cannot reveal the original token. If no original remains, stop the instance and explicitly run `.venv/bin/python scripts/local_runtime.py repair-room-env --rotate-room-token`; this revokes the old room-owner token, preserves member tokens and writes the new private file. A private `room-token.pending.env` protects recovery across an interrupted rotation: retain it, never publish it. The command never silently rotates during setup.
