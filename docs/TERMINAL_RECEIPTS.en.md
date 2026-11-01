# Optional terminal receipt to Grok

The automatic server hook is disabled by default. The explicit operator command below is also available. It does not create a
routine or subscription. Configure a routine yourself and explicitly authorize
its use before running this command. Inherit `ROUNDTABLE_URL`,
`ROUNDTABLE_ROOM`, `ROUNDTABLE_AGENT`, `ROUNDTABLE_TOKEN` for an authorized scoped
reader, and `GROK_ROUTINE_URL`, `GROK_ROUTINE_KEY`, `GROK_ALLOWED_HOST` from your
trusted secret manager. The command never parses credential files. Do not put
secrets in command arguments, source control, or chat.

```sh
"${ROUNDTABLE_HOME}/.venv/bin/python" "${ROUNDTABLE_HOME}/terminal_receipts.py" \
  TASK_ID --dispatch-terminal --wait 600 \
  --ledger "${ROUNDTABLE_HOME}/data/terminal-receipts.db"
```

`--wait` defaults to zero and is bounded to 86400 seconds. It polls only the
specified task through the existing authenticated loopback client, roughly once
per second with a bounded total wait using the client wait implementation.
If the task is still nonterminal, nothing is reserved or sent. Supported states
are `completed`, `failed`, `timeout`, and `cancelled`. The payload contains only
`task_id` and `status`, never instructions, results, tokens, or lease values.
The existing Grok transport validates an allowlisted HTTPS host, rejects private
DNS results and pins the public IP in direct mode. Explicit proxy mode instead trusts proxy DNS and uses hostname CONNECT. TLS verification and redirect rejection apply in both modes. HTTP 200 means routine acceptance only.

The durable SQLite ledger reserves **one attempt per room/task before network
I/O**, across command invocations and concurrent processes sharing that ledger.
Repeated terminal reads or later status changes do not resend. An exception is
reported as `uncertain`, with no automatic retry. A crash after reservation but
before sending can lose the receipt; a crash after remote acceptance can leave
the local outcome uncertain. This provides at-most-one attempt, **not exactly-once
delivery**. Once reserved, a definite network failure remains recorded and is not automatically retried, just like an uncertain transmission. Retain the
same ledger across restarts; deleting it or selecting another ledger can cause
duplicate sends. Do not change ledgers to retry an uncertain outcome. Check the
native routine history yourself before deciding what to do.

Nothing here starts Codex, sends task assignments, or establishes native Grok
identity. Mock receipt tests prove only the protocol and local deduplication.

## Automatic server hook (explicit opt-in)

Before starting a new `server.py` process, inherit these settings from trusted
operator configuration. Do not reload or change an existing server implicitly:

```sh
export ROUNDTABLE_TERMINAL_NOTIFICATIONS=1
export ROUNDTABLE_TERMINAL_ROOM=YOUR_TEST_ROOM_ID
export ROUNDTABLE_TERMINAL_ORIGIN=grok-origin
export ROUNDTABLE_TERMINAL_LEDGER="${ROUNDTABLE_HOME}/data/terminal-receipts.db"
# GROK_ROUTINE_URL / GROK_ROUTINE_KEY / GROK_ALLOWED_HOST: secret-manager references
"${ROUNDTABLE_HOME}/.venv/bin/python" "${ROUNDTABLE_HOME}/server.py"
```

The configured origin must be a current member. Only tasks with that room,
`bot:<origin>` and the still-current membership epoch qualify. The worker reads
committed terminal task events on its own read-only database connection. On first
enable it saves the latest event cursor and skips old terminal backlog; existing
running tasks and future tasks can notify when they become terminal. The cursor
is durable, so downtime events after first enable are observed on restart. The
ledger must be retained; changing it resets both cursor and delivery reservations.
A task that is retried after a failed terminal state does not receive a second
receipt. Membership and status are checked at selection time; a revoke after
selection cannot retract a network operation already begun.

The server starts the worker before accepting requests and stops it with a bounded
one-second join. Network I/O holds neither a Store lock nor an open SQLite
transaction. Each dispatch has a 20-second total wait, including DNS; at most four
transport threads may be in flight. A stuck DNS/socket call retains its slot until
it returns. Timeout or capacity exhaustion consumes the reservation and reports
uncertainty with no retry. Timeout and worker shutdown cancel the real Grok transport and shut down its
tracked socket. Cancellation checkpoints after DNS, TCP and TLS prevent a late
POST when those stages unblock. A request already transmitted cannot be retracted;
remote acceptance remains uncertain. These bounds keep the local service responsive.
Set the enable flag to `0` for the next process start to disable the hook. With the
flag absent, no worker starts and no routine configuration is parsed.

Both modes honor `ROUNDTABLE_TERMINAL_LEDGER` and default to
`data/terminal-receipts.db` relative to the working directory. Use the same
absolute ledger path for automatic and manual delivery.

Configuration preflight runs before a receipt reservation: missing explicit proxy in a proxy environment or invalid proxy configuration is `definitely_not_sent`, does not consume an attempt, and leaves the worker cursor pending. Uncertain network sends retain their reservation and are never replayed. Transient worker failures recover with stop-aware exponential backoff from 0.1 to 30 seconds; authenticated doctor capabilities expose `terminal_worker` state/reason/retry_seconds and `outbound_backend` mode without URLs or secrets. Ledger creation uses exclusive mode-0600 files and mode-0700 new directories, without changing process-global umask or existing permissions/data.
