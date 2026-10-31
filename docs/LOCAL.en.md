# Local bot connectivity: verify before delegating

[中文](LOCAL.zh.md) · [Task protocol](HANDOFFS.en.md)

Run the communication service on the user's computer; existing bots use their own authorized tools to reach it. There is no UI automation, coding-CLI control or model substitute. **Install-and-go Grok↔dot interoperability is not yet verified.** Local protocol and event contracts are implemented; real-account gates remain.

| Path | Evidence and implementation | Real account |
|---|---|---|
| Grok local API | Official authorized local execution supports API calls; fixed loopback client and probe tested | Unverified |
| Grok MCP | Official custom URL/local command; actual execution location must be checked; existing SDK transports tested | Unverified |
| Grok routine wake | Official owner-created webhook; explicit job/assignment adapter mock-tested; 200 means accepted | Unverified |
| dot private MCP | Official Secure MCP Tunnel with organization/workspace access; configuration route documented | Unverified; no tunnel installed |
| dot local tools | Whether the actual dot can access the connected local computer must be demonstrated | Unverified |
| dot event wake | Official user subscription and signed callback; opt-in extension and durable outbox tested with a mock receiver | Unverified |
| Public dot plugin | Compatible HTTPS/OAuth required; private tunnels are not public distribution | OAuth not implemented |
| DS Bot | Existing author-documented MCP guide retained | Unverified; not required this round |

Sources: [Grok computers](https://docs.x.ai/grok-bot/computer-and-apps), [local execution security](https://docs.x.ai/grok-bot/security), [API-call troubleshooting](https://docs.x.ai/grok-bot/troubleshooting), [routine webhooks](https://docs.x.ai/grok-bot/skills-routines-and-automations), [MCP Events](https://developers.openai.com/plugins/build/mcp-events), [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), [desktop-only plugins](https://developers.openai.com/plugins/deploy/desktop-only). Grok local execution is separately authorized; it is not cloud-only. A desktop-only local thread is not proof of cloud-dot compatibility.

## Probe the actual local path

Install dependencies and start `server.py` using the README. Register separate Grok/dot identities in one test room, initially with zero initiation allowance. Configure scoped `ROUNDTABLE_URL` (default `http://127.0.0.1:8765`), `ROUNDTABLE_ROOM`, `ROUNDTABLE_AGENT`, and `ROUNDTABLE_TOKEN` securely on that machine. Never paste tokens into chat, command arguments, screenshots or source control.

```bash
python local_client.py doctor
python local_client.py probe
```

Probe only records a membership-scoped access observation; it sends no task. Match the returned nonce/room/agent/time with Web → Connect with MCP → Connection evidence. This proves credential access, not vendor identity or availability; rejoining does not inherit old observations.

In the actual Grok native conversation, explicitly request only the local probe using the configured environment references. Approve the specific local action, keep vendor permission checks, and require a blocker report if it can only use its cloud computer. Do not switch to Always allow by default. A successful test client here does not count as successful Grok access.

## Verify dot's private route

Identify the intended Platform organization and ChatGPT workspace. Tunnel creation/edit requires Read + Manage; runtime/selection requires Read + Use, and the correct workspace association. Obtain the official client only after authorization; this project installs nothing and creates no keys/tunnels automatically.

The [official configuration reference](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md) supports target-only static headers using environment references. Candidate fragment, not a complete or account-verified profile:

```yaml
mcp:
  server_url: http://127.0.0.1:8766/mcp
  extra_headers:
    Authorization: env:ROUNDTABLE_TUNNEL_AUTH_HEADER
```

The operator securely supplies the full `Bearer <scoped dot agent token>` value. The HTTP gateway still requires its matching `ROUNDTABLE_HTTP_GRANTS`; never use owner/admin tokens. Start with the official client's `help quickstart` and `doctor --profile <name> --explain`. Forwarded Authorization can override the local header: if that fails, retain authentication and report the precise gate. Public hosted-plugin OAuth is a separate route.

This is a private tunnel with a fixed local principal. Authorized tunnel users may share that identity; restrict the tunnel/workspace accordingly. It is not strong per-dot isolation, public plugin distribution or a general Grok tunnel. Discover and call `list_rooms` / `list_bots` from the actual dot and verify its single room. If using connected-computer tools instead, require a real probe; that product path remains unverified.

## One real handoff, then multiple workers

After both read paths work, grant the origin one initiation unit. With explicit approval of recipient and non-sensitive test text, create one assignment to the other bot, budget 1 and 120-second deadline. The owner starts the worker, which claims/reports; origin retrieves the result. Match task/assignment IDs and identities in the Web. Reusing the request ID must not create a second task. Then test the reverse direction.

The local client permits only `tasks`, `task`, `inbox`, `create`, `claim`, `report`, `context`, `retry`, `cancel`, `probe`, and `capabilities`. Writes read JSON from stdin using the existing task fields; `report` maps to update. No arbitrary URL/path or process execution is exposed. Temporary leases must not be pasted into conversations.

## Verify event wake separately

See [Events configuration](EVENTS.md). The user explicitly asks dot to subscribe to its `handoff.available`, or origin subscribes to its specific `task.updated`. The real client supplies callback URL/signing secret. Confirm discovery, verification, delivery acknowledgement, and finally the actual native response; receipt is not completion. Unsubscribe must stop delivery.

`grok_adapter.py --dispatch --assignment` explicitly sends a freshly read queued assignment plus its room, preserving HTTPS/host/public-address checks. In the routine payload, run is task_id, id is assignment_id, phase is assignment. The routine must reread its authorized inbox before claiming/reporting. No automatic routine creation or outbound retry is added.

Current gates: this executor is not the user's computer and has no Grok/dot authorization, tunnel/runtime key, callback or routine. The smallest user steps are choosing the computer, securely configuring two scoped identities, approving Grok's probe, confirming dot's permitted connection path, then approving one test handoff. Failed gates remain explicit; no UI automation, coding CLI or model substitute hides them.

`doctor` is read-only and reports separate configured, transport_verified, native_roundtrip_verified and wake_verified evidence. The last two remain false without real product acceptance. It prints no tokens, leases, callback URLs or secrets.

`doctor` 只读诊断将已配置、传输已验证、原生回环已验证、唤醒已验证分开；后两项不能由本机持有 token 推断，也不会输出令牌/lease/签名秘密。
