# Bounded wait and read-only roundtrip

Use an already authorized scoped environment: `ROUNDTABLE_URL` (loopback),
`ROUNDTABLE_ROOM`, `ROUNDTABLE_AGENT`, `ROUNDTABLE_TOKEN`. Do not paste secrets into
commands or chat. No secret files are parsed by these commands.

```sh
"${ROUNDTABLE_HOME}/.venv/bin/python" "${ROUNDTABLE_HOME}/local_client.py" wait TASK_ID --timeout 600
"${ROUNDTABLE_HOME}/.venv/bin/python" "${ROUNDTABLE_HOME}/local_client.py" roundtrip --worker dot --timeout 600 --evidence "${ROUNDTABLE_HOME}/data/roundtrip.json"
"${ROUNDTABLE_HOME}/.venv/bin/python" "${ROUNDTABLE_HOME}/local_client.py" doctor --evidence "${ROUNDTABLE_HOME}/data/roundtrip.json"
```

Replace `TASK_ID` and `dot` with the authorized task and registered member ID.
`roundtrip` is an explicit write: it creates one read-only nonce-return assignment,
with dispatch budget 1 and task deadline 600 seconds. The origin needs one unit of
initiation allowance. It does not subscribe or wake a vendor itself. The worker
must already be authorized to receive this test. It must return the exact nonce
without executing commands, reading files, or creating Codex work.

`wait` polls terminal state without cancelling on local timeout. The entire wait budget is monotonic, including DNS, connection and trickling
responses. On expiry the client interrupts the active socket. An uninterruptible
DNS call retains one of four bounded worker slots until it finishes; exhausted
capacity fails closed without spawning additional workers.
A timed-out roundtrip leaves a private atomic evidence file with status unknown;
inspect the original task instead of blindly repeating creation. A successful
command prints task/assignment IDs and a bounded result summary. Add `--test` for
synthetic workers. No claim lease or credential is saved in evidence.

Doctor validates evidence scope against the configured room/member and re-reads
the authenticated task and assignment. Completed state plus the expected result
digest establishes only protocol correlation. It never proves vendor identity.
Failed, timed-out, unknown, mismatched, and unavailable evidence cannot establish
success. Evidence is local, editable operator data, not a signed audit record.

Native and wake acceptance are separate optional **operator attestations**. After
personally observing the actual native conversation and (separately) event-driven
wake, the operator may add `operator_observations.native_roundtrip` and/or
`operator_observations.wake` to the evidence JSON. Each entry needs
`confirmed: true`, `source: "operator"`, the same `task_id` and `assignment_id`,
and a finite Unix `observed_at` timestamp after the protocol observation and not
in the future. Only non-test, correlated completed evidence accepts these entries.
Doctor labels them local operator attestations and keeps
`vendor_identity_verified: false`. Do not mark synthetic tests as native success.

Reproduce the isolated contract test (no actual Grok/dot account):

```sh
cd "${ROUNDTABLE_HOME}"
.venv/bin/python -m unittest discover -s tests -p test_roundtrip.py -v
```

It uses ephemeral loopback ports, real HTTP MCP SDK initialize/tool calls, Events
subscription/challenge with an injected mock callback, and a synthetic Dot worker
receiving, claiming, reporting progress and completion. This verifies the
contract, not real provider delivery or native wake.
