# MCP Events extension / 事件扩展

This opt-in implementation follows the [official MCP Events contract](https://developers.openai.com/plugins/build/mcp-events) for user-requested subscriptions. It extends the pinned official SDK's **Streamable HTTP** endpoint; the SDK still implements core initialization/tools. The draft event methods are implemented by `EventsHTTP`, not claimed as built-in SDK support or MCP 2.0 support. The bare gateway CLI does not advertise Events without `--events-db`, and the stdio bridge never advertises them. Managed setup explicitly enables discovery with an empty deny-all host list; it does not subscribe or approve an outbound host. 裸网关需显式 events-db；托管 setup 启用空白名单发现，但不订阅、不批准外发。

```bash
# Configure existing ROUNDTABLE_URL and scoped ROUNDTABLE_HTTP_GRANTS securely first.
python mcp_http.py --events-db data/events.db --event-host EXACT_APPROVED_CALLBACK_HOST
```

The placeholder hostname must be replaced with the actual trusted product callback hostname after operator review; no wildcard/default host is provided. Callback URL and signing secret come from the real subscription request, not a fabricated vendor endpoint. The service remains loopback-only. These switches do not deploy HTTPS, create a tunnel, issue OAuth tokens or connect a real account.

## Notification format / 通知格式

There is exactly one event, `roundtable.notification`, subscribed with `{}`. New notification kinds never need a new subscription. The webhook body sent to Grok uses the same object, but a webhook bot (`grok-routine`) receives only three kinds: `task.finished` for tasks it created, `task.assigned` once per attempt when an assignment for it is queued (new, retried or lease expired), and `message`. It receives no `task.updated` and no worker-side `cancelled`; a report on a cancelled task is rejected.

| Field | Rule |
|---|---|
| `kind` | One of `task.assigned`, `task.updated`, `task.finished`, `message`. Receivers ignore unknown kinds. |
| `id` | Task kinds: 24 lowercase hex task ID. `message`: decimal message ID string (no leading zero). |
| `status` | `task.finished`: required, one of `completed`/`failed`/`timeout`/`cancelled`. `task.updated`: the task event kind (for example `claimed`, `progress`, `context`). `task.assigned`/`message`: absent. |

No other fields are sent: no task text, message body, result, token or lease. On receipt, read the inbox (`receive_assignments`, `receive_messages`, `get_task`) and act by kind.

| Kind | Who receives it |
|---|---|
| `task.assigned` | The worker of a new or requeued assignment that is still queued |
| `task.updated` | The task's origin, for changes made by someone else |
| `task.finished` | The task's origin, when the task reaches a finished state; also, with status `cancelled`, the worker of an assignment that was still queued or working when the task was cancelled |
| `message` | An authorized topic member selected for a bounded message wake (delivery alone does not imply wake; system notices never wake) |

Examples: `{"kind":"task.assigned","id":"0123456789abcdef01234567"}`, `{"kind":"task.finished","id":"0123456789abcdef01234567","status":"completed"}`, `{"kind":"message","id":"42"}`.

只有一个事件 `roundtable.notification`，参数 `{}`；以后新增 kind 不需要重新订阅。Grok webhook body 用同一格式，但 webhook bot（`grok-routine`）只收三种：自己发起的任务结束时收 `task.finished`；派给它的 assignment 进入排队（新派、重试、租约过期）时，每次尝试收一次 `task.assigned`；以及 `message`。它收不到 `task.updated`，也收不到执行方的 `cancelled`，任务取消后再报进度会被拒绝。字段只有 `kind`、`id`、可选 `status`，不带任何正文。收到后读收件箱，按 kind 处理。


The same authenticated `/mcp` accepts `events/list`, `events/subscribe`, `events/unsubscribe`. A successful initialize adds `capabilities.events`. Event data contains only kind, id and optional status; retrieve authorized text/results using tools. An event cannot increase permissions or directly run a worker. Each notification is scoped to the authenticated member, and self-authored changes are excluded.

Implementation limits: maximum 10 subscriptions per principal / 100 total; default and maximum lifetime seven days, no permanent grant; canonical subscription identity; 60-second non-sliding verification cache; short challenge lifetime; 60-second dual-signature key rotation. Expired/revoked subscriptions stop delivery. The private SQLite subscription/outbox file survives restart and is required to have private permissions on Unix. It stores callback URLs and signing secrets in plaintext: protect its directory and backups. No real secrets were configured in development tests.

A cursor over the existing task event store drives the **internal outbox**; it is not a client polling or streaming delivery mode. Events are sent as signed HTTPS callbacks only. One request per event, stable ID across at most three attempts, fresh timestamp/signature, bounded backoff. 410 ends the subscription, 413 and other permanent rejections are not retried. A 2xx is receipt, never proof of bot execution. Event IDs support receiver deduplication; external exactly-once execution is not promised. New subscriptions start at the current event boundary. Protocol cursor is null: no replay request API is offered. Existing unexpired subscriptions resume persisted outbox work after restart; expired subscriptions lose undispatched work.

Callback verification and delivery both require exact approved HTTPS hosts on port 443, hostname TLS verification and no redirects. Direct mode validates all locally resolved target IPs as public and pins the chosen address. Ordinary proxy environment variables still fail closed. Explicitly set `ROUNDTABLE_OUTBOUND_PROXY` (or legacy `ROUNDTABLE_EVENT_PROXY`) to an operator-trusted HTTP CONNECT proxy to opt in (no proxy credentials). CONNECT uses the canonical callback hostname; the trusted proxy resolves it. No target DNS lookup occurs locally, and the local process cannot prove the proxy destination IP is public. TLS and Host retain that hostname. No direct fallback occurs. Private/loopback callbacks are rejected. Tests inject a receiver object; they do not weaken production URL validation or contact a real product.

`tests/test_mcp_events.py` covers real SDK initialization plus raw documented draft JSON-RPC methods on the same authenticated HTTP server, signature contract, failed verification, filters, self-notification exclusion, duplicate refresh, bounded verification cache, rotation, restart, expiry, revocation, retries and permanent rejection. Ordinary `test_mcp_http.py` tests still cover default transport authorization and room isolation.

中文：用户须先在 dot 明确要求监听。当前为默认关闭的 HTTP Events 扩展，不是 stdio 的自动唤醒能力。群/成员权限来自认证，任务通知仅带 ID 和状态类别；正文仍需工具按权限读取。内部持久 outbox 扫描不等于向 ChatGPT 提供 polling/streaming Events。订阅、签名、验证、轮换、重启和重试已做契约测试；另有一次受控真实 webhook 触发 Dot 领取并回传只读 nonce 的验收，不代表 Codex 执行或 Grok routine 已验证。回调 host 必须由操作者明确批准；普通代理环境变量仍默认拒绝；可显式设置 `ROUNDTABLE_OUTBOUND_PROXY`（兼容 `ROUNDTABLE_EVENT_PROXY`） 使用可信 HTTP CONNECT 代理，不支持代理凭据。CONNECT 使用规范化域名，由可信代理解析，目标不在本机解析；本机无法证明代理最终目标 IP 为公网。TLS 和 Host 保留原域名，不回退直连。直连仍执行公网 IP 校验与固定。订阅数据库含签名秘密，需保护文件和备份。公网 OAuth/私有 tunnel 配置与本扩展是不同接线层，详见 [本机指南](LOCAL.zh.md)。

### Concurrent delivery and cancellation

Network I/O runs outside the subscription database lock. Each scan uses at most four workers; verification also has four slots. Callback transport has four bounded slots and a configurable total caller deadline (default 20 seconds via `ROUNDTABLE_EVENT_TIMEOUT`) covering DNS, TLS, headers and body, including slow trickle responses. Uninterruptible DNS retains its slot until resolution returns and cannot subsequently send after cancellation; saturation fails closed rather than creating unbounded threads. In-flight requests may already have reached their destination when unsubscribe returns, but subscription-generation checks discard their receipts and prevent resurrection or retries after cancellation/refresh.

中文：回调总期限通过 `ROUNDTABLE_EVENT_TIMEOUT` 配置，默认 20 秒，覆盖 DNS、CONNECT、TLS、响应头与正文。超时取消后不会在迟到的 TLS 握手完成时继续发送。

## First discovery and renewal / 首次发现与续期

**Safe bootstrap:** an empty allowlist now permits Events discovery and rejects all subscribe challenges before DNS/network/persistence. Inspect the real platform request's safe hostname rejection, independently verify it, explicitly approve the exact host and restart only the managed gateway. See [managed setup](SETUP_AUTOMATION.en.md). No placeholder or wildcard approval.

When changing Events capabilities, refresh the existing ChatGPT plugin's tools/metadata and rediscover event sources/schema in the actual conversation. `roundtable.notification` uses `{}`; any other name or argument is rejected. Tool discovery alone does not confirm event discovery or a subscription. After a real host rejection, verify only the safely logged candidate hostname against the intended platform interaction, explicitly approve the exact host, and restart only the affected gateway while preserving its private Events DB. No universal callback hostname is assumed. This implementation retains `-32015` for callback/verification failures; platform pre-creation errors are a separate layer.

Confirm successful subscription state before creating test work. On an ambiguous create result, inspect existing platform automations/subscriptions before retrying; do not create duplicates or substitute a polling schedule. Default and maximum TTL are seven days. The client/product must renew before expiry; the operator must verify that behavior. This service has no universal renewal controller, and a new subscription does not replay past events. Real event-triggered Dot receipt → claim → exact read-only nonce completion has been observed in a controlled test; each installation must verify its own route. See [acceptance levels](ROUNDTRIP.en.md).

**安全首次接入：** 空白名单现在允许 Events 发现，但在 DNS/网络/持久化前拒绝全部订阅 challenge。读取平台真实请求的安全 hostname 拒绝日志，另行核验后精确批准，仅重启受管理的网关。见[自动配置](SETUP_AUTOMATION.zh.md)。不批准占位域名或通配符。

能力变化后，刷新既有 ChatGPT 插件的工具/metadata，再在实际会话重新发现事件来源/schema。`roundtable.notification` 参数为 `{}`，其他事件名或参数一律拒绝；工具存在不等于事件已发现或已订阅。真实请求被 host 拒绝后，只提取安全日志中的候选 hostname，核实平台来源后精确批准，仅重启相应网关并保留私有 Events DB；不假定任何全局固定回调域名。callback/验证失败继续使用 `-32015`，平台创建前错误是另一层。

订阅成功后再造测试任务。创建结果不确定先查已有 automation/subscription，不重复创建，不用轮询替代事件。默认及最长 TTL 均七天，由产品/客户端续订，操作者需核验；服务没有通用续订控制器，新订阅不重放过去事件。受控实测已观察到真实事件触发 Dot 领取并原样回报只读 nonce，每个安装仍需独立验收，见[验收层级](ROUNDTRIP.zh.md)。
## Backend availability / 后端可用性

Authorization is tri-state: a complete matching 200 authorizes; 401/403 revoke; network/5xx/malformed 200 preserve existing subscriptions with `backend_unavailable`, without sending while unavailable. A five-second backoff bounds repeated checks. Expiry and cancellation still apply; post-delivery uncertainty in authorization does not replay an acknowledged event. Create/renew/cancel/expire/revoke logs contain status names only, never URL, secret or principal. Initial/renewal requests with uncertain authorization are rejected, not newly authorized.

授权为三态：完整且身份匹配的 200 明确授权；401/403 撤权；连接/5xx/非法 200 保留已有订阅并记 `backend_unavailable`，不可用期间不发事件，检查退避五秒。取消/过期照常，投递后权限检查暂不可用不重发已确认事件。创建/续订/取消/过期/撤权日志只有状态名，不含 URL、secret、principal。授权不确定的创建/续订请求拒绝，不获得新授权。

Subscriptions default/max to seven days. Platform renewal must be verified, and toggling an automation does not guarantee another subscribe request. 订阅默认/上限七天，须验证平台续订；切换 automation 开关不保证重新 subscribe。

## Reported live acceptance / 报告的真实验收

The installation maintainer reports, relayed through Grok, that one real installation received Grok terminal routine receipts and renewed subscriptions automatically before expiry. This documentation update did not independently reproduce either result; see [the evidence gap](../VERIFICATION.md#maintainer-reported-acceptance). The earlier read-only nonce test alone did not prove routine delivery or Codex execution. Every deployment still needs to inspect actual renewal records/refresh time and correlate routine results with its authorized task. If a subscription is lost, inspect existing platform state before toggling or recreating; afterwards verify real subscribe/renewal records, not merely an enabled UI switch.

安装维护者经 Grok 报告：一次真实安装已收到 Grok 终态 routine 回执，并在到期前自动续订。本次文档更新未独立复现这两项结果，见[证据缺口](../VERIFICATION.md#maintainer-reported-acceptance)。此前只读 nonce 测试本身不证明 routine 投递或 Codex 执行。每个部署仍应检查实际续订记录/刷新时间，并关联已授权任务与 routine 结果。订阅丢失时先核平台已有状态，再视情况关开或重建；之后确认真实 subscribe/续订记录，不以 UI 开关启用代替验证。
