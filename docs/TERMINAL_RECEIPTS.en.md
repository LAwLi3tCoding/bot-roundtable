# Optional terminal receipt to Grok

This is an operator command, not an enabled server hook. It does not create a
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
per second; the final HTTP request may add up to the client's network timeout.
If the task is still nonterminal, nothing is reserved or sent. Supported states
are `completed`, `failed`, `timeout`, and `cancelled`. The payload contains only
`task_id` and `status`, never instructions, results, tokens, or lease values.
The existing Grok transport validates an allowlisted HTTPS host, rejects private
DNS results, pins the public IP, verifies TLS and rejects proxy environments and
redirects. HTTP 200 means routine acceptance only.

The durable SQLite ledger reserves **one attempt per room/task before network
I/O**, across command invocations and concurrent processes sharing that ledger.
Repeated terminal reads or later status changes do not resend. An exception is
reported as `uncertain`, with no automatic retry. A crash after reservation but
before sending can lose the receipt; a crash after remote acceptance can leave
the local outcome uncertain. This provides at-most-one attempt, **not exactly-once
delivery**. Even a preflight network failure consumes the reservation. Retain the
same ledger across restarts; deleting it or selecting another ledger can cause
duplicate sends. Do not change ledgers to retry an uncertain outcome. Check the
native routine history yourself before deciding what to do.

Nothing here starts Codex, sends task assignments, or establishes native Grok
identity. Mock receipt tests prove only the protocol and local deduplication.
