# State, logs, migration and cleanup

Code and private state now have separate lifetimes. `ROUNDTABLE_HOME` still means the **checkout**, never state. Do not run `git clean -xfd`, delete, or re-clone an old checkout before migrating/backing up its `data/`: Git ignores those files but clean can permanently delete them.

## Default locations

The default instance name is `default`. Managed commands accept `--name <INSTANCE_NAME>`; `ROUNDTABLE_INSTANCE_NAME` supplies the same name to standalone commands. Names contain only letters, digits, `_` and `-`, start with a letter/digit, and are at most 64 characters.

| Platform | Default state directory | Default managed logs |
| --- | --- | --- |
| macOS | `~/Library/Application Support/bot-roundtable/<INSTANCE_NAME>` | `~/Library/Logs/bot-roundtable/<INSTANCE_NAME>` |
| Linux | `${XDG_STATE_HOME:-~/.local/state}/bot-roundtable/<INSTANCE_NAME>` | `<STATE_DIRECTORY>/logs` |
| Windows | `%LOCALAPPDATA%\bot-roundtable\<INSTANCE_NAME>` | `<STATE_DIRECTORY>\logs` (managed process supervision/migration not supported on Windows) |

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
| `migration.json` | Source/target file sizes and SHA-256 verification metadata | 0600; contains no credential values; private metadata nonetheless |
| `<LOG_DIRECTORY>/<component>.log[.1–.3]`, `*.log.lock` | Filtered bounded status records and single-writer locks | 0600; unknown vendor text is discarded; not raw HTTP/body logs |
| `launchd/*.plist` | Optional un-loaded launchd templates | 0600; no secret values; inspect before any separate loading action |

Managed logs default to **10 MiB per file and three backups**, plus the active file. Configure initial setup with `--log-max-bytes <BYTES>` (256–1 GiB) and `--log-backups <COUNT>` (1–20). Re-running setup does not change existing settings; for an existing stopped instance, deliberately edit those non-secret numeric fields in private `instance.json`. Each supervisor holds one exclusive log lock throughout writing/rotation; a second writer fails rather than racing. The Tunnel FIFO passes through the same bounded writer and is removed on supervised shutdown. Oversize records are dropped. A crash can leave a stale FIFO; startup validates ownership/type before replacing it.

Setup selects two distinct available loopback ports unless `--server-port`/`--mcp-port` is supplied. Ports are saved in `instance.json`, member URLs and the profile; status/doctor report the actual loopback URLs. Selection is a probe, not a reservation until startup: if another process wins the race, startup refuses the occupied port and never adopts/kills that process. Review the configuration or deliberately initialize another isolated instance. Standalone default ports remain 8765/8766 for compatibility; automatic selection is managed setup only.

## Migrate a stopped managed instance

`migrate-state` is for the existing managed state format. Heterogeneous legacy JSON/env snapshots instead use [import-legacy](ONBOARDING_RUNTIME.en.md#import-a-legacy-snapshot). Never use either operation on a live installation. Stop the old instance **using its original checkout/manager**, and separately prevent any old launchd/login automation from starting it again. The migration command does not stop processes or unload jobs.

```sh
# From the OLD checkout, with its original process ownership:
sh scripts/down.sh --state-dir '<OLD_CHECKOUT>/data/local'
# From the NEW checkout:
.venv/bin/python scripts/local_runtime.py migrate-state \
  --from '<OLD_CHECKOUT>/data/local' --name demo
# Inspect the returned verification result before starting the migrated instance.
.venv/bin/python scripts/local_runtime.py doctor --name demo
```

`--from` is mandatory. `--state-dir '<NEW_EMPTY_DIRECTORY>'` can override the destination. Migration locks the source lifecycle and destination, refuses live/reused/unverifiable PIDs, unconfirmed descendant cleanup, occupied service ports, incomplete initialization, symlinks/junctions/special files and uncheckpointed SQLite sidecars. Copy is through checked file descriptors with source identity checks, size/hash verification and a final source recheck. Verified private staging is atomically published; ordinary failures remove only that attempt's staging. An abrupt crash can leave private `.migrate-*` remnants for offline review. No old files are deleted. Migration never changes callback approval, proxy, ports, member permissions or existing receipt history.

Transient lifecycle/health/FIFO files are not adopted as new process ownership. Routine configuration and the existing receipt ledger are preserved for a **deliberate later startup**, unlike import-legacy's pending routine/receipt suppression policy. External custom log directories are not moved; back them up separately. Old logs inside state remain archived there; future logs use the new configured log directory. Keyring metadata retains the original OS entry through a validated binding; migration does not read/write the OS secret, revoke old access or create a replacement key. Both directories can still reference the same credential: **do not run old and new instances simultaneously**.

A repeated migration is successful only when source and target still match every recorded size/hash and file list. Subsequent startup, key rotation, or other changes can make the marker stale; that is an explicit mismatch, not permission to overwrite or reset the target. Keep the source until acceptance and backup are confirmed. Never delete the new receipt ledger to resolve a mismatch.

## Checkout relocation and stable startup

State schema is checked independently of checkout location. After moving/re-cloning code, use the same state directory; `up` reports `code_location_changed_run_rebind` instead of losing state or starting a duplicate instance. With the old instance stopped:

```sh
.venv/bin/python scripts/local_runtime.py rebind --name demo
sh scripts/render-launchd.sh --name demo
# Optional explicit private output directory: --output '<REVIEW_DIRECTORY>'
```

Rebind updates only the code-location record after stopped-instance checks, not credentials or network approvals. Render defaults to `<STATE_DIRECTORY>/launchd` and refuses overwriting existing files; select a fresh review directory to re-render. Plists use `/bin/sh <CHECKOUT>/scripts/up.sh`, which resolves the current `.venv/bin/python` (or explicitly supplied `ROUNDTABLE_PYTHON`). Rebuilding the venv **at the same path** needs no re-render. Moving the checkout still requires rebind and new plist review/replacement. Nothing loads launchd automatically; identity-based labels and Homebrew/system PATH remain.

Standalone `server.py` now defaults to `<STATE_DIRECTORY>/roundtable.db`, `local_client.py` evidence to `<STATE_DIRECTORY>/roundtrip.json`, and terminal receipt commands to `<STATE_DIRECTORY>/terminal-receipts.db`, independent of cwd. Existing explicit `--db`, `--evidence`, `--ledger` and corresponding environment variables take precedence. Standalone admin files default beside the selected DB in `admin-credentials`; `--admin-state` overrides. Do not point standalone and managed managers at one database.

## Backup and uninstall

Stop the chosen instance with its own manager; verify stopped/cleanup status before taking a consistent private copy of state and separately configured logs. Preserve permissions, DBs, receipt ledger, keyring recovery access and migration metadata together; do not upload to Git, chat, or public artifact storage. OS keyring references are not self-contained backups of keyring secrets.

To uninstall, stop only that instance, separately disable any launchd/login job you previously installed, cancel its actual platform subscription, and revoke its Tunnel/runtime key and bot credentials through their approved account controls. Then deliberately remove only that instance's state/log directories after deciding whether private history should be retained. Removing code or state does not revoke remote keys or delete OS keyring entries. Scripts do not perform account revocation, recursive deletion, system power changes, or automatic launchd loading/unloading.
