# 针对性安全复核（2026-10-31）

本轮使用独立 reviewer 检查实际源文件，并由实现者复核修复。它不是完整渗透测试或生产安全认证。

## 已修复的可复现问题

1. `roundtable.py` / `Store.reply`：旧逻辑先在独立事务中调用 expire，再取得回复写锁。reviewer 在 expire 后插入等待，可使已超过 deadline 的回复继续入库并完成讨论。现将 deadline 检查放到回复写事务内；超时状态提交后再返回 409，避免异常回滚超时标记。`tests/test_roundtable.py::test_expired_callback_checks_deadline_in_write_transaction` 验证超时状态保留、没有 bot 消息、没有推进轮次。
2. `grok_adapter.py` / `GrokWebhook.dispatch`：Python `ipaddress` 对 `224.0.0.1` 与 `ff02::1` 返回 is_global=True，原单一检查未排除组播。现同时拒绝 multicast、reserved 与非 global 地址。`tests/test_grok_security.py` 覆盖组播、保留地址、云元数据地址、IPv6 loopback 及 IPv4-mapped loopback，并断言未创建 TLS 连接。

3. `server.py`：reviewer 发现原 socket timeout 设置晚于 headers 解析；现移到 Handler.setup，覆盖请求行与 header 阶段。
4. `grok_adapter.py`：reviewer 指出手工提交保存的旧 job 会启动外部工作；现 dispatch 前拒绝过期、非有限或非法 deadline，并测试拒绝时不解析 DNS。适配器仍无法离线判断未过期 job 是否已被 stop，操作人须先读取当前 mailbox。

## 逐文件检查

- `server.py`：管理员创建房间、room 路由和 agent 路由使用不同认证范围；所有 agent 路由先按 room+agent 验证。Host/Origin 约束、输入大小上限、固定静态文件映射与错误响应均检查。HTTP access log 禁用，异常日志不含 body、Authorization 或 URL。
- `roundtable.py`：token 摘要对比；job 查询必须同时匹配 id+room+agent；sender/source 取自服务端身份；重复相同回复不增轮次，冲突回复拒绝；budget 仅为 1–20 整数；stop 与 reply 使用同一 RLock/事务。独立 reviewer 额外运行 100 次 stop/reply 竞争验证，均停止且没有 pending work；同房间错误 agent 凭据返回 403，冒用其他 agent 的 job 返回 404。
- `grok_adapter.py`：URL 由 operator 指定，保留 HTTPS、精确主机名白名单、443、无 URL 凭据、原域名 TLS 校验、禁止跳转及不自动重试。直连模式检查全部解析地址，并固定已校验的公网 IP。未配置显式出站代理且存在 `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY` 等环境变量（含小写形式）时，失败关闭，拒绝发送。配置 `ROUNDTABLE_OUTBOUND_PROXY`（或兼容 `ROUNDTABLE_EVENT_PROXY`）时，以主机名 CONNECT，由代理解析 DNS；本机不再执行公网 IP 钉扎，也无法证明最终 IP 为公网，这是 trusted proxy DNS 信任边界。日志不输出 key，CLI 对异常使用通用错误文本。
- `static/app.js` / `static/index.html`：文本使用 textContent，凭据只在页面内存；没有内容驱动的工具执行或动态 URL。浏览器实测 script 文本不执行。
- `tests/test_roundtable.py` / `tests/test_grok_security.py`：认证隔离、关联回调、重复并发回复、停止、失败、重启不重放、预算、超时、SSRF 地址与固定 IP、重定向拒绝的回归测试。

## 剩余边界

单进程本机 MVP，无公网 TLS 网关、账户体系、令牌撤销、速率限制、资源配额、数据加密或多副本协调。响应历史尚未分页，长时间大量使用可增加内存/磁盘消耗。停止 relay 不会取消已启动的外部 bot 工作。Grok adapter 没有真实端到端联调，HTTP 200 不代表完成，回程需要 owner 接线。通用 mailbox 的外部消费者必须自己保存 dispatch 去重状态，不承诺外部执行 exactly-once。官方 dot 通道未实现，也没有绕过 owner 限制。

## MCP / 群管理升级复核（2026-10-31）

独立 reviewer 再次检查 `roundtable.py`、`server.py`、`mcp_bridge.py` 与前端，实际复现并修复：

1. **嵌套事务部分提交**：第二个成员插入失败时，旧嵌套 connection context 已提前提交房间及第一个成员。改用嵌套 SAVEPOINT，整次建群失败原子回滚；有 SQLite 失败触发器回归测试。
2. **撤销认证竞态**：旧 token 校验后到操作前，成员可被移除/重加并获得新额度，旧请求误用了新成员权限。现在认证与操作同处 Store 锁内，解析/网络写在锁外；并发回归验证撤销语义。
3. **人类身份混淆**：不再允许新 Bot ID 为 `user`；前端同时要求 `source=human` 和 `sender=user`，兼容防护历史数据。

新增测试覆盖累计发起额度、错误 agent 抢答、Lead 自调用拒绝、Lead 最低/总预算、修改活跃群拒绝、旧令牌/回调撤销与真实 MCP receiver 收发。正式 SDK 三个独立客户端模拟发起者/Lead/接收者，经过 initialize/tools/call，验证角色、关联、重复回调、跨群隔离和撤销。没有执行真实产品联调。

本版不实现或调用任何编码 CLI runner。Bot 消息不能更改身份、群成员、Lead 或工具权限。Agent 能读取其已加入群的共享历史；job 只携带当前讨论。MCP 本身不提供自动唤醒，现有远程 Bot 的账号接线仍需 owner 单独完成。

### English review summary

An independent reviewer reproduced and fixed partial commits from nested transactions, a membership-revocation authentication race, and the reserved human identity display ambiguity. SAVEPOINTs now make group creation atomic; authentication and operations share a lock while network I/O stays outside; bot ID `user` is reserved and the UI additionally checks message source. Regression tests include real SDK MCP clients, agent-scoped receiving/replying, cumulative allowances, Lead budgets, replay, revocation and isolation. These tests use synthetic messages, not live provider accounts. The remaining local-only/production limitations described above still apply.

## Native handoff review — 2026-10-31

Independent review covered `handoffs.py`, `server.py`, `mcp_bridge.py` and `static/handoffs.js`, with ten new security regressions in `tests/test_handoff_security.py`. Fixed recursive cancellation of descendants, preventing failed tasks from reviving after cancellation, pending inbox truncation, parent/root deadline checks inside writes, unclaimable budget-exhausted retries, rejoined-worker epoch mismatches, and unbounded context additions. Final reports remain possible after progress reaches its event cap.

A second pass reproduced a 2 MB bridge truncation after 26 legitimate large historical tasks. Task listings now return bounded previews; full instructions/results/artifacts are available through scoped `get_task`, and an explicit 8 MB bridge cap replaces silent JSON truncation (allowing bounded single-task Unicode event pages). A regression creates 30 large histories and checks the bounded list while full task data remains available.

UI review reproduced stale task A controls surviving while task B loaded. Reset now clears details and disables actions until B is loaded. Mutations capture their room/task and do not apply late responses to another selection. Budget changes invalidate the render signature; cancelled/timed-out work no longer offers retry. Global errors remain visible in task mode and task errors are translated. Browser tests hold a query in flight and verify no stale instruction or enabled cancel remains.

Authentication supplies identity; no caller-provided actor/room replaces it. Assignment views filter other workers' instructions/results/events. Revocation uses membership epochs. Bot results and artifacts stay inert text. Temporary leases are hashed in assignments but included in idempotency claim receipts: the database/backup remains sensitive and is not encrypted. External exactly-once execution, remote cancellation and product-level isolation behind shared connectors are not guaranteed. Parent status aggregates its own assignments rather than an entire dependency graph.

原生交接独立复核修复了递归取消、旧成员 epoch、预算与过期竞态、上下文数量、历史列表过大和跨任务旧 UI 操作残留。验证仅使用合成身份与本机服务；未配置真实 Bot、OAuth 或公网服务。

## Local connectivity / Events boundary review — 2026-10-31

The new client accepts only loopback origins, validated fixed room/agent IDs and a finite operation map. Doctor performs a read-only authenticated capabilities request and returns evidence levels without credentials. Probe observes only possession of a scoped credential; no vendor identity is attested. Grok assignment dispatch preserves the prior public-address/HTTPS checks, never claims a worker lease and treats 200 only as acceptance.

The Events extension remains inside existing Host/Origin/auth middleware. Scope is checked against the task store before callback verification. Event callbacks require an exact canonical hostname allowlist, HTTPS and TLS hostname verification; redirects and proxy bypass are rejected. Direct mode validates and pins public addresses. Explicit trusted-proxy mode delegates destination DNS to the proxy and cannot prove the resolved IP is public locally. JSON-RPC errors and delivery failures are categorized without raw URL/secret leakage. Subscription IDs include authenticated token epoch; revocation/expiry prevents future dispatch. A non-sliding bounded verification cache and finite retry queue were regression-tested. Same-instance callbacks are serialized, outside the Hub Store lock. A delivery already in flight cannot be recalled after revocation/cancel, and the remote receiver must deduplicate stable event IDs.

Subscription SQLite stores callback signing secrets in plaintext, with private Unix permissions required. Protect the directory/backups; Windows ACL verification is not implemented or tested. No production per-IP rate limiter or independent multi-process broker is provided. Ambient-only proxy configuration fails closed; an explicit outbound proxy selects the documented trusted proxy DNS boundary. A shared tunnel's fixed local header is a shared principal, not per-dot identity. Public-plugin OAuth and real native acceptance remain outstanding. This is code/contract review, not a vendor security certification or real-account integration report.

显式代理模式以用户选择的代理作为 DNS/路由信任边界，不在本机解析目标域名，也不能在本机证明最终目标 IP 公网。直连模式保留公网校验与 IP 固定；两者都保留精确域名白名单、原主机 TLS 校验及禁止重定向。

## Local browser Bot management and chat timeline — 2026-11-03

The new `bot-management` routes require a session originally issued through the login-code exchange with Cookie delivery. They reject admin, room, Bot and bearer UI credentials, including a bearer-issued UI credential copied into a Cookie header. Requests must arrive from the loopback peer with the exact loopback Host; mutations also require the matching Origin. Forwarded headers are rejected. Existing credential APIs retain their prior authorization rules. This is a local browser capability, not a new remote account role.

Independent review found a revocation race between the Cookie-provenance check and the later session-validity check: the latter could observe an invalid session while the route still accepted the earlier provenance result. The route now requires both checks to pass, and a deterministic regression covers revocation between them. Management mutations and credential checks execute under the Store lock; response I/O stays outside it. Bot creation, membership, avatar/wake settings and allowance changes use one transaction so a rejected value cannot leave a partial Bot behind.

A newly generated Bot token appears only in the successful creation response. The database stores its digest; registry, management and workspace reads do not return the plaintext. The browser does not persist it in browser storage, clears it when its dialog closes or the page is hidden or left, and closes all dialogs when the session ends. Copying requires pressing the copy button. Clipboard contents are outside this clearing guarantee. Losing the response or closing the token display cannot be repaired by retrieving the token again.

`connect-bot` imports that token through hidden terminal input, verifies the exact room/Bot access endpoint, and saves it in the private local environment file before updating the runtime configuration. It does not issue or rotate a credential, and it refuses to overwrite an environment file for a different identity. A retry can reuse the saved credential. It never restarts a process. Wake-method changes require this local synchronization and a separately authorized restart; routine URLs and keys remain local-only inputs.

Suspension is checked by Bot authentication, task membership/claim/report operations, message sending, wake recipients and allowance consumption. The event gateway revalidates access before delivery; queued routine notifications recheck the Bot state before dispatch. Already-running network requests and external work cannot be recalled. Restoration permits the existing identity to resume. Deletion requires the current name as confirmation, revokes active assignments and credential digests, and preserves registry/history records for attribution. Registry identity/name/avatar/wake and suspension/deletion are global to that Bot across legacy workspaces; allowance remains per workspace.

Task bubbles read the existing scoped task-query endpoint. The new presentation does not broaden assignment visibility, copy private legacy topics into the shared timeline, change notification kinds, or turn task text into executable content. Bot messages, instructions and results remain inert text. Filters are presentation preferences saved per workspace, not access controls. Only explicit mentions and task assignment cause notifications.

Verification uses synthetic identities and isolated test servers: `tests/test_bot_management.py` covers Cookie provenance, credential rejection, Origin/proxy boundaries, revocation timing, atomic creation, one-time secrets, suspension and retained history; `tests/test_connect_bot.py` covers hidden import and safe retry; browser tests cover token clearing, confirmation and management availability. Screenshot generation replaces every displayed credential with an explicit redacted placeholder before capture. These checks are not a real-provider integration or a complete security certification.
