# State, logs, migration and cleanup

Code and private state now have separate lifetimes. `ROUNDTABLE_HOME` still means the **checkout**, never state. Do not run `git clean -xfd`, delete, or re-clone an old checkout before migrating/backing up its `data/`: Git ignores those files but clean can permanently delete them.

## Default locations

The default instance name is `default`. Managed commands accept `--name <INSTANCE_NAME>`; `ROUNDTABLE_INSTANCE_NAME` supplies the same name to standalone commands. Names contain only letters, digits, `_` and `-`, start with a letter/digit, and are at most 64 characters.

| Platform | Default state directory | Default managed logs |
| --- | --- | --- |
| macOS | `~/Library/Application Support/bot-roundtable/<INSTANCE_NAME>` | `~/Library/Logs/bot-roundtable/<INSTANCE_NAME>` |
| Linux | `${XDG_STATE_HOME:-~/.local/state}/bot-roundtable/<INSTANCE_NAME>` | `<STATE_DIRECTORY>/logs` |
| Windows | `%LOCALAPPDATA%\bot-roundtable\<INSTANCE_NAME>` | `<STATE_DIRECTORY>\logs` (managed process supervision not supported on Windows) |

Managed state precedence: **`--state-dir` > `ROUNDTABLE_STATE_DIR` > platform default**. An explicit custom state directory uses `<STATE_DIRECTORY>/logs`, including macOS. XDG_STATE_HOME must be absolute. Windows requires LOCALAPPDATA. No permission repair, global environment change, or system security setting is performed. Directories are POSIX 0700; regular files and FIFO are 0600. Windows administrator persistence uses current-user ACL checks; platform path resolution alone does not establish Windows runtime support.

```sh
.venv/bin/python scripts/local_runtime.py paths --name demo
.venv/bin/python scripts/setup-local.py --name demo --allowance 1
sh scripts/up.sh --name demo --without-tunnel
.venv/bin/python scripts/local_runtime.py status --name demo
```

`paths` reports prospective resolved paths, not credentials. Keep the same name or explicit state directory on every command. A first default setup that detects legacy checkout `data/local` refuses silent creation of a replacement identity; migrate deliberately, or explicitly choose another new instance. Status/doctor warn about state within the checkout, macOS Documents/Desktop/Downloads/iCloud locations, code in those protected locations, and a detected legacy directory. Legacy detection checks existence only, not its secret contents. These are location warnings, not a TCC permission probe; moving state outside Documents does not exempt code remaining there from macOS background-process restrictions.

## File inventory and permissions

| Files | Purpose | Protection / backup handling |
| --- | --- | --- |
| `admin.json` (legacy `admin.env`), `room.env`, `<member>.env` | Administrator, room owner and individual member credentials | 0600; encrypted/offline private backup, never upload |
| `runtime-key.env`, `routine.json`, `routine.pending.json` | Tunnel runtime key and explicitly approved/pending routine configuration | 0600; retain permissions, expiry and revocation responsibility |
| `roundtable.db`, `events.db`, `terminal.db` | Task/history, subscriptions/signing secrets and at-most-once receipt ledger | 0600; stop/checkpoint before backup; keep DB and ledger together |
| `instance.json`, `tunnel.yaml`, `roundtrip.json` | Identity/schema, scoped profile references and evidence | 0600; profile references may be safe but state as a whole is private |
| `incomplete.json`, `recovery.json`, `prepared.json` | Interrupted initialization recovery (may contain credentials) | 0600; offline inspection, not automatic migration |
| `.lock`, `.admin.lock`, component `*.pid.json` / `*.started.json` / `*.child.json` / `*.stop.json`, `health.url`, `tunnel-child.pid`, `tunnel-log.pipe` | Lifecycle coordination and transient health/FIFO transport | 0600; do not transfer process ownership by copying these |
| `<LOG_DIRECTORY>/<component>.log[.1–.3]`, `*.log.lock` | Filtered bounded status records and single-writer locks | 0600; unknown vendor text is discarded; not raw HTTP/body logs |
| `launchd/*.plist` | Optional un-loaded launchd templates | 0600; no secret values; inspect before any separate loading action |

Managed logs default to **10 MiB per file and three backups**, plus the active file. Configure initial setup with `--log-max-bytes <BYTES>` (256–1 GiB) and `--log-backups <COUNT>` (1–20). Re-running setup does not change existing settings; for an existing stopped instance, deliberately edit those non-secret numeric fields in private `instance.json`. Each supervisor holds one exclusive log lock throughout writing/rotation; a second writer fails rather than racing. The Tunnel FIFO passes through the same bounded writer and is removed on supervised shutdown. Oversize records are dropped. A crash can leave a stale FIFO; startup validates ownership/type before replacing it.

Setup selects two distinct available loopback ports unless `--server-port`/`--mcp-port` is supplied. Ports are saved in `instance.json`, member URLs and the profile; status/doctor report the actual loopback URLs. Selection is a probe, not a reservation until startup: if another process wins the race, startup refuses the occupied port and never adopts/kills that process. Review the configuration or deliberately initialize another isolated instance. Standalone default ports remain 8765/8766 for compatibility; automatic selection is managed setup only.

## Manually transfer a stopped instance

The project provides no automatic migration/import command. An operator must review old layouts and perform a one-time transfer; no script interprets or rewrites old credentials. Do not run `git clean -xfd` before a verified private backup of old `data/`.

1. Stop the source with its original manager and prevent launchd/login jobs from restarting it. Confirm server, MCP, Tunnel and descendants are stopped. Do not copy a running SQLite database.
2. Full managed `down` checks stopped ownership, then runs `PRAGMA wal_checkpoint(TRUNCATE)` for private `*.db` files, including task, Events and receipt databases. It refuses open databases. If `lsof` is absent, managed shutdown still verifies process ownership and termination, then returns `checkpoint_skipped_database_inspection_unavailable` in `warnings` and skips checkpointing. WAL files are preserved. Install `lsof` before retrying maintenance; migration still fails closed without inspection. Component-only shutdown does not checkpoint. For an older manager or standalone server, use SQLite maintenance tooling on the stopped source to checkpoint every database, close connections and verify no `-wal` remains. If busy/uncertain, stop and investigate; never delete a WAL to force success.
3. Copy into a new empty private destination while preserving POSIX 0700 directories/0600 files (or reviewed current-user Windows ACLs). Reject symlinks, special files and unsafe ownership. Retain administrator, room/member credentials, databases, existing receipt ledger and approved configuration together. Do not copy transient PID/started/child/stop/health/FIFO files as active process ownership. Keep private logs separately as needed; this project performs no log relocation.
4. Verify each copied regular file by size and SHA-256 before any intentional configuration edits. Keep manifests private; do not print credential contents. Review old schema, absolute paths, log destination, code location and profile references; there is no automatic conversion of heterogeneous legacy JSON/env layouts. Keyring references are path-bound and need separately reviewed OS credential handling, not blind metadata copying.
5. Preserve callback approval, proxy and receipt history without enabling new permissions. If receipt history is missing or uncertain, keep terminal notifications disabled until reconciled; never reset the ledger to replay old tasks. Do not run old and new copies simultaneously. Use `rebind` only for an already compatible managed configuration whose checkout moved; it does not convert old layouts.
6. Validate the new private configuration and scoped access deliberately, retain the old directory and backup until acceptance, then decide cleanup separately. The project never deletes the original or performs this transfer for you.

## Checkout relocation and stable startup

State schema is checked independently of checkout location. After moving/re-cloning code, use the same state directory; `up` reports `code_location_changed_run_rebind` instead of losing state or starting a duplicate instance. With the old instance stopped:

```sh
.venv/bin/python scripts/local_runtime.py rebind --name demo
sh scripts/render-launchd.sh --name demo --output '<NEW_PRIVATE_REVIEW_DIRECTORY>'
# Optional explicit private output directory: --output '<REVIEW_DIRECTORY>'
```

Rebind updates only the code-location record after stopped-instance checks, not credentials or network approvals. Render defaults to `<STATE_DIRECTORY>/launchd` and refuses overwriting existing files; select a fresh review directory to re-render. Plists use `/bin/sh <CHECKOUT>/scripts/up.sh`, which resolves the current `.venv/bin/python` (or explicitly supplied `ROUNDTABLE_PYTHON`). Rebuilding the venv **at the same path** needs no re-render. Moving the checkout still requires rebind and new plist review/replacement. Nothing loads launchd automatically; identity-based labels and Homebrew/system PATH remain.

Standalone `server.py` and `start-local.sh server` default to `<STATE_DIRECTORY>/manual/roundtable.db`, `local_client.py` evidence to `<STATE_DIRECTORY>/roundtrip.json`, and terminal receipt commands to `<STATE_DIRECTORY>/terminal-receipts.db`, independent of cwd. Existing explicit `--db`, `--evidence`, `--ledger` and corresponding environment variables take precedence. Standalone admin files default beside the selected DB in `admin-credentials`; `--admin-state` overrides. The standalone `admin_credentials.py` CLI defaults to `<STATE_DIRECTORY>/manual/admin-credentials` too; for a custom server database, pass its actual admin directory explicitly with that CLI’s `--state-dir`. Do not point standalone and managed managers at one database.

## Backup and uninstall

Stop the chosen instance with its own manager; verify stopped/cleanup status before taking a consistent private copy of state and separately configured logs. Preserve permissions, DBs, receipt ledger, keyring recovery access together; do not upload to Git, chat, or public artifact storage. OS keyring references are not self-contained backups of keyring secrets.

To uninstall, stop only that instance, separately disable any launchd/login job you previously installed, cancel its actual platform subscription, and revoke its Tunnel/runtime key and bot credentials through their approved account controls. Then deliberately remove only that instance's state/log directories after deciding whether private history should be retained. Removing code or state does not revoke remote keys or delete OS keyring entries. Scripts do not perform account revocation, recursive deletion, system power changes, or automatic launchd loading/unloading.

Managed component logs now record a numeric child exit code and fixed diagnostic categories (missing dependency, import failure, permission denial, missing file, database failure, occupied address). Raw exception text is still discarded. Fast child exits drain bounded output after confirmed exit. This improves diagnosis; the reported Linux startup failure has not been reproduced natively and is not attributed to missing `lsof` without evidence.
