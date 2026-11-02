# MCP Events extension / 事件扩展

This opt-in implementation follows the [official MCP Events contract](https://developers.openai.com/plugins/build/mcp-events) for user-requested subscriptions. It extends the pinned official SDK's **Streamable HTTP** endpoint; the SDK still implements core initialization/tools. The draft event methods are implemented by `EventsHTTP`, not claimed as built-in SDK support or MCP 2.0 support. No event capability is advertised by default or by this project's stdio bridge.

```bash
# Configure existing ROUNDTABLE_URL and scoped ROUNDTABLE_HTTP_GRANTS securely first.
python mcp_http.py --events-db data/events.db --event-host EXACT_APPROVED_CALLBACK_HOST
```

The placeholder hostname must be replaced with the actual trusted product callback hostname after operator review; no wildcard/default host is provided. Callback URL and signing secret come from the real subscription request, not a fabricated vendor endpoint. The service remains loopback-only. These switches do not deploy HTTPS, create a tunnel, issue OAuth tokens or connect a real account.

| Event | Filter | Scope |
|---|---|---|
| `handoff.available` | `{}` | New/requeued assignment for this authenticated member only |
| `task.updated` | `{"task_id":"…"}` | Task originated by this authenticated member; self-authored changes excluded |

The same authenticated `/mcp` accepts `events/list`, `events/subscribe`, `events/unsubscribe`. A successful initialize adds `capabilities.events`. User-facing event data contains only task_id, assignment_id and kind; retrieve authorized text/results using tools. An event cannot increase permissions or directly run a worker. These two narrow events avoid automatic broadcasts and reply-driven re-dispatch.

Implementation limits: maximum 10 subscriptions per principal / 100 total; default and maximum lifetime one hour, no permanent grant; canonical subscription identity; 60-second non-sliding verification cache; short challenge lifetime; 60-second dual-signature key rotation. Expired/revoked subscriptions stop delivery. The private SQLite subscription/outbox file survives restart and is required to have private permissions on Unix. It stores callback URLs and signing secrets in plaintext: protect its directory and backups. No real secrets were configured in development tests.

A cursor over the existing task event store drives the **internal outbox**; it is not a client polling or streaming delivery mode. Events are sent as signed HTTPS callbacks only. One request per event, stable ID across at most three attempts, fresh timestamp/signature, bounded backoff. 410 ends the subscription, 413 and other permanent rejections are not retried. A 2xx is receipt, never proof of bot execution. Event IDs support receiver deduplication; external exactly-once execution is not promised. New subscriptions start at the current event boundary. Protocol cursor is null: no replay request API is offered. Existing unexpired subscriptions resume persisted outbox work after restart; expired subscriptions lose undispatched work.

Callback verification and delivery both require exact approved HTTPS hosts on port 443, hostname TLS verification and no redirects. Direct mode validates all locally resolved target IPs as public and pins the chosen address. Ordinary proxy environment variables still fail closed. Explicitly set `ROUNDTABLE_OUTBOUND_PROXY` (or legacy `ROUNDTABLE_EVENT_PROXY`) to an operator-trusted HTTP CONNECT proxy to opt in (no proxy credentials). CONNECT uses the canonical callback hostname; the trusted proxy resolves it. No target DNS lookup occurs locally, and the local process cannot prove the proxy destination IP is public. TLS and Host retain that hostname. No direct fallback occurs. Private/loopback callbacks are rejected. Tests inject a receiver object; they do not weaken production URL validation or contact a real product.

`tests/test_mcp_events.py` covers real SDK initialization plus raw documented draft JSON-RPC methods on the same authenticated HTTP server, signature contract, failed verification, filters, self-notification exclusion, duplicate refresh, bounded verification cache, rotation, restart, expiry, revocation, retries and permanent rejection. Ordinary `test_mcp_http.py` tests still cover default transport authorization and room isolation.

中文：用户须先在 dot 明确要求监听。当前为默认关闭的 HTTP Events 扩展，不是 stdio 的自动唤醒能力。群/成员权限来自认证，任务通知仅带 ID 和状态类别；正文仍需工具按权限读取。内部持久 outbox 扫描不等于向 ChatGPT 提供 polling/streaming Events。订阅、签名、验证、轮换、重启和重试已做契约测试；另有一次受控真实 webhook 触发 Dot 领取并回传只读 nonce 的验收，不代表 Codex 执行或 Grok routine 已验证。回调 host 必须由操作者明确批准；普通代理环境变量仍默认拒绝；可显式设置 `ROUNDTABLE_OUTBOUND_PROXY`（兼容 `ROUNDTABLE_EVENT_PROXY`） 使用可信 HTTP CONNECT 代理，不支持代理凭据。CONNECT 使用规范化域名，由可信代理解析，目标不在本机解析；本机无法证明代理最终目标 IP 为公网。TLS 和 Host 保留原域名，不回退直连。直连仍执行公网 IP 校验与固定。订阅数据库含签名秘密，需保护文件和备份。公网 OAuth/私有 tunnel 配置与本扩展是不同接线层，详见 [本机指南](LOCAL.zh.md)。

### Concurrent delivery and cancellation

Network I/O runs outside the subscription database lock. Each scan uses at most four workers; verification also has four slots. Callback transport has four bounded slots and a configurable total caller deadline (default 20 seconds via `ROUNDTABLE_EVENT_TIMEOUT`) covering DNS, TLS, headers and body, including slow trickle responses. Uninterruptible DNS retains its slot until resolution returns and cannot subsequently send after cancellation; saturation fails closed rather than creating unbounded threads. In-flight requests may already have reached their destination when unsubscribe returns, but subscription-generation checks discard their receipts and prevent resurrection or retries after cancellation/refresh.

中文：回调总期限通过 `ROUNDTABLE_EVENT_TIMEOUT` 配置，默认 20 秒，覆盖 DNS、CONNECT、TLS、响应头与正文。超时取消后不会在迟到的 TLS 握手完成时继续发送。

## First discovery and renewal / 首次发现与续期

**Known bootstrap limitation:** Events startup currently requires a nonempty exact callback allowlist. There is no supported discovery-only/deny-all mode. If the product supplies its callback hostname only in `events/subscribe.delivery` and no actual hostname is available from trusted platform configuration beforehand, a new installation is blocked. Do not fabricate a callback, authorize a placeholder host, use wildcards, or disable validation to bridge this gap. The [setup guide](DOT_SETUP.en.md) documents the boundary and the supported steps once a trusted allowlist exists.

When changing Events capabilities, refresh the existing ChatGPT plugin's tools/metadata and rediscover event sources/schema in the actual conversation. `handoff.available` uses `{}` and `task.updated` requires `task_id`. Tool discovery alone does not confirm event discovery or a subscription. After a real host rejection, verify only the safely logged candidate hostname against the intended platform interaction, explicitly approve the exact host, and restart only the affected gateway while preserving its private Events DB. No universal callback hostname is assumed. This implementation retains `-32015` for callback/verification failures; platform pre-creation errors are a separate layer.

Confirm successful subscription state before creating test work. On an ambiguous create result, inspect existing platform automations/subscriptions before retrying; do not create duplicates or substitute a polling schedule. Default and maximum TTL are one hour. The client/product must renew before expiry; the operator must verify that behavior. This service has no universal renewal controller, and a new subscription does not replay past events. Real event-triggered Dot receipt → claim → exact read-only nonce completion has been observed in a controlled test; each installation must verify its own route. See [acceptance levels](ROUNDTRIP.en.md).

**首次接入已知限制：** 当前启用 Events 必须有非空精确 callback 白名单，没有支持的 discovery-only/deny-all 模式。如果产品只在实际订阅请求中提供 hostname，且无法提前从可信平台配置取得，首次安装会阻塞。不要构造 callback、批准占位域名、使用通配符或关闭验证来跨过此限制。[接入指南](DOT_SETUP.zh.md)说明边界及已有可信白名单后的流程。

能力变化后，刷新既有 ChatGPT 插件的工具/metadata，再在实际会话重新发现事件来源/schema。`handoff.available` 参数为 `{}`，`task.updated` 必填 `task_id`；工具存在不等于事件已发现或已订阅。真实请求被 host 拒绝后，只提取安全日志中的候选 hostname，核实平台来源后精确批准，仅重启相应网关并保留私有 Events DB；不假定任何全局固定回调域名。callback/验证失败继续使用 `-32015`，平台创建前错误是另一层。

订阅成功后再造测试任务。创建结果不确定先查已有 automation/subscription，不重复创建，不用轮询替代事件。默认及最长 TTL 均一小时，由产品/客户端续订，操作者需核验；服务没有通用续订控制器，新订阅不重放过去事件。受控实测已观察到真实事件触发 Dot 领取并原样回报只读 nonce，每个安装仍需独立验收，见[验收层级](ROUNDTRIP.zh.md)。
