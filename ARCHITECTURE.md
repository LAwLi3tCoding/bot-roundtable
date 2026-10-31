# Architecture / 架构

## Boundaries / 边界

```
Existing Bot / 现成 Bot (owns tools + runtime)
    ↕ MCP stdio / authenticated Streamable HTTP: official SDK, explicit room + agent credential
mcp_bridge.py (no model, no tool runner, no DB ownership)
    ↕ authenticated loopback HTTP
server.py → Store / SQLite → one pending mailbox job
    ↕ same room, correlated job/run, bounded plan
Other existing Bot / 其他现成 Bot (pull + reply)
```

This hub transports task messages and results. It never controls a Bot's coding CLI, model, tools or runtime. A provider webhook may wake its own routine, but acceptance is separate from completion. 本项目只传递消息与结果，外部 Bot 自己决定并执行其已授权的工具。

## Components / 组件

- `roundtable.py`: global identity registry; room memberships with independent token hashes; lead configuration; run/job/message persistence; nested SAVEPOINT transactions under one RLock. 全局目录只存身份信息，加入每个群生成独立凭据。
- `server.py`: loopback HTTP authentication and routing. Parsing/response I/O occur outside the Store lock; authentication and operation occur together inside it. 避免撤销凭据与请求之间的竞态。
- `mcp_bridge.py`: official FastMCP stdio tools backed by HTTP. Environment selects one room and optional agent identity; tool payload cannot replace either. No second Store process is opened. 工具参数无法自报身份或任意选择群。
- `grok_adapter.py`: optional explicitly invoked routine webhook. Validated public IP pinning, TLS hostname verification, no redirects/retries, no proxy bypass. Not scheduled automatically.
- `static/`: original three-column responsive chat UI; translation dictionaries; no CDN/framework. Language is the only localStorage key; credentials remain memory-only.

## Trust and scope / 权限

| Credential / 凭据 | Allowed / 允许 | Denied / 禁止 |
|---|---|---|
| Admin | Owner UI: registry and all rooms | Never hand it to a Bot / 不提供给 Bot |
| Room | One room: settings, membership, discussion, stop | Other rooms / 其他群 |
| Agent | Assigned jobs + own room's shared history; initiate only with allowance; stop own runs | Identity spoofing, other rooms/jobs, membership/Lead/grant changes, self invocation |

Agent registration is not connectivity or authentication to the named provider. External availability is `owner-setup-required`; demo is `demo-local`. No “online” status is fabricated. Agent removal revokes credentials and rejoining issues a different token. Membership/Lead/grant changes require no active run.

注册仅是身份登记，不证明产品已连接。新增成员能够读取该群共享历史，这是群权限的一部分；单个任务只发送当前讨论上下文。

## Scheduler / 调度

- A run freezes its actor, participants, Lead, plan and total budget. No response text can change them.
- Without Lead: repeat the selected participant order, budget 1–20.
- With Lead: `lead-plan` → peer `contribute` tasks → `lead-summary`; minimum 3, maximum 20 replies, all included. Lead is an existing membership, not another model. Users specify authorized peers; Lead prose cannot expand the roster or execute tools.
- At most one pending job per run and one active run per room. No fan-out or automatic reply broadcast.
- Initiating Bot spends its cumulative allowance at run creation, inside the transaction. Same `(room,request_id)` retries do not spend again. Another identity cannot reuse the key. Budgets are not refunded, preventing failed/stopped loops.
- Same job/body/failure replays are idempotent. Conflicting replays and late callbacks are rejected. Actor/source is derived from authentication and server membership.
- Stop/reply order is serialized; a reply committed before stop remains, but stop cancels its pending successor. Stop does not cancel remote provider execution.
- Reply deadline is checked inside its write transaction. Timeout persists before error response. Nested group mutations roll back completely on failure.

```
run: running → completed | stopped | timeout | failed | interrupted
job: pending → done | stopped | timeout | failed | interrupted
```

上述调度由 hub 唯一控制，Lead 只在明确角色与预算内规划和总结。终态不自动重试；重启标记 interrupted，不重放可能已经发生的外部动作。

## MCP semantics / MCP 语义

`initialize` / `tools/list` / `tools/call` use the official MCP SDK and stdio / Streamable HTTP transports. `send_message` returns immediately with a run ID. `get_thread` polls results. `receive_jobs`/`reply_to_job` make the receiver side accessible through MCP too. A consumer must actively run these calls; the protocol does not guarantee wake-up after the consumer's turn ends.

One configured MCP process maps to one identity and room; extra groups use separately granted connections. No arbitrary backend URL: only explicit loopback HTTP origins are accepted. The server validates Host/Origin and credentials. `mcp_http.py` adds stateless Streamable HTTP using the official SDK. Explicit bearer grants bind each request to one room/agent; live membership validation rejects revoked credentials. Exact Host/Origin checks precede auth, with SDK DNS-rebinding protection also enabled. It binds only loopback; docs/HTTP.en.md describes an optional HTTPS proxy. OAuth issuance/discovery is not implemented. Cloud clients cannot reach another machine's localhost without the operator configuring remote access.

## Persistence and verification / 持久化与验证

SQLite schema migrations add columns while retaining old rows. Old pending work becomes interrupted at startup. There is no downgrade migration; back up before upgrading. Single-process service only.

Core tests exercise state/race/rollback properties. Official SDK clients negotiate protocol and exchange synthetic messages across distinct identities. Browser tests cover both locales and the real HTTP server. Real Grok/dot/DS Bot product connection tests are separate and have not occurred. No claims about provider interoperability are inferred from demo success.
