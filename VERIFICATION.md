# Verification / 验证记录

<a id="maintainer-reported-acceptance"></a>

## Maintainer-reported acceptance / 维护者报告的验收

2026-11-02: the installation maintainer reports, relayed through Grok, observing Grok terminal routine receipts and automatic subscription renewal before expiry in one real installation. The reviewed repository verification/setup documents contain no independently correlated receipt/task record or before/after renewal timestamp evidence for this new report. Record it as maintainer-reported acceptance, not a newly reproduced test or a universal platform guarantee. Each deployment must verify its own routine result, actual subscription/renewal records and refresh time. This documentation update sent no callback/routine, inspected no secret runtime logs and did not verify Codex execution.

2026-11-02：安装维护者经 Grok 报告，在一次真实安装中已观察到 Grok 终态 routine 回执及到期前自动续订。本轮审阅的仓库验收/接入文档没有可独立关联的回执/任务记录或续订前后时间证据，因此记录为维护者报告，不写成新一轮亲测或平台普遍保证。每个部署仍需核验自己的 routine 结果、实际订阅/续订记录与刷新时间。本次文档更新未发送 callback/routine、未检查含秘密运行日志，也未验证 Codex 执行。

## Managed setup and subscription availability / 本地自动配置与订阅可用性

2026-11-02: **165 unit/MCP/security tests passed** locally on Python 3.12 (30 new contracts). Ruff lint and format checks passed for 40 files; mypy passed for 16 source files; Python compilation and all three JavaScript syntax checks passed. Both Chromium product/handoff regressions passed against synthetic loopback services. The Mac handoff test used the already-installed Playwright Chromium through CHROMIUM_PATH because its legacy default is a Linux path. No browser installation or personal browser session was used.

New coverage includes idempotent 0600 initialization, incomplete-state refusal, symlinks/permissions, explicit proxy child environments, hidden key/routine input, plist path escaping, occupied ports/foreign and stale PIDs, real server/MCP subprocess lifecycle, failed PID publication, descendant cleanup, missing stop outcomes, lifecycle-lock availability during waits, scoped subscription counts, and a synthetic Tunnel executable exercising FIFO log filtering/readyz/stop. Events tests cover strict authorization responses, unavailable-backend retention/backoff/recovery, no replay after acknowledged delivery, deny-all discovery without DNS/challenge, and sanitized lifecycle logs. CLI tests exercise positional task/context IDs, JSON compatibility/conflicts and bounded open stdin.

Independent code review found and closed initialization publication ordering, startup rollback, raw/split-log leakage, PGID reuse, uncertain cleanup reporting and long-wait locking issues. Synthetic tests prove these local contracts, not vendor identity or automatic wake. This development run did not create account rights, use real keys, subscribe, invoke routines, restart existing services or load launchd. No remote CI is claimed for local-only commits.

2026-11-02：本机 Python 3.12 全量 **165 项通过**（新增30项）；Ruff/format检查40文件、mypy检查16源文件、编译及三项JS语法检查通过，两套真实浏览器回归使用合成本机服务通过。覆盖幂等/0600/中断/符号链接、子进程代理、隐藏秘密输入、plist路径、端口/PID归属、真实子进程启动停止/后代清理、停止结果缺失、等待不占锁、订阅范围、模拟Tunnel FIFO/readyz及Events三态/空白名单/日志和CLI输入边界。独立审查发现的安全生命周期问题已修复。没有真实账号权限、真实key、订阅/routine、现有服务重启或launchd操作；合成通过不等于厂商原生验收，本地提交不声称远端CI通过。


The macOS sleep-prevention increment was checked against the installed `man caffeinate`: idle assertion `-i`, AC-only system assertion `-s`, and PID lifetime `-w`. Five added tests execute a fake binary only, covering default managed startup, opt-out, actual fake-child status/server binding, release on server exit, unsupported/missing binary, startup failure and foreign-PID refusal. Independent incremental review passed. No real caffeinate or power-setting command was executed; hardware assertion state was not accepted as verified. The two macOS-specific fake-process tests are skipped on other platforms; skip behavior is separately covered.

防睡眠增量核对了本机 `man caffeinate` 的 -i/-s/-w 语义，新增5项测试仅执行假程序，覆盖默认/关闭、实际假子进程状态与server绑定、server退出释放、不支持/缺程序、启动失败和拒杀外来PID。独立增量审查通过。未执行真实 caffeinate 或电源修改命令，不声称硬件断言验收；非Mac跳过两项Mac假进程生命周期测试，另有平台跳过行为测试。

## Local connectivity + event contracts — current feature branch

2026-10-31: local Python 3.12 checks cover **80 unit/MCP/security tests**, Ruff lint/format, mypy on ten production modules, compilation and JavaScript syntax. Both actual Chromium scripts passed, including the bilingual connection evidence panel and unchanged native handoff flows. CI additionally runs Python 3.13; consult the published commit's Actions result.

New tests: real loopback scoped client/probe/doctor, no arbitrary URL or operation, revocation/epoch evidence reset, existing task claim/report through the thin client, Grok assignment payload with acceptance-only semantics. Events tests use official SDK initialization/tools plus documented draft event JSON-RPC methods on the same authenticated HTTP endpoint; callback transport is an injected synthetic receiver, never a real vendor callback. Covered signing exact bytes, tampering mismatch, failed challenge, idempotent refresh, non-sliding verification cache, origin-only filtered updates without self-trigger, retry bounds/stable IDs, secret rotation, restart, expiry/revocation, 410/413, private/reserved-address rejection and no redirects. Events IDs include a persistent local-store namespace.

No native Grok/dot account connection, local-user computer access, tunnel runtime, public OAuth, real webhook delivery, or real bot task was performed. Doctor reports native_roundtrip_verified=false and wake_verified=false even when local transport succeeds. The product is ready for the explicit account acceptance gates in docs/LOCAL.zh.md; simulated callbacks are not a substitute for that acceptance. Main remains unchanged.

## Native bot handoffs — current feature branch / 当前功能分支

2026-10-31: **62 Python unit/MCP/security tests passed** locally with Python 3.12, including real official SDK stdio and Streamable HTTP initialization/list-tools/calls. The new HTTP test uses two independent workers, distinct assignments, progress, failure/retry, fan-in, cancellation and scope rejection; actual owner HTTP snapshots/events match MCP task IDs and events. Core tests cover idempotency payload conflicts, concurrent claim/report/cancel, lease expiry, restart recovery, membership epochs, parent budgets/depth, deadlines and bounded list payloads. The independent reviewer added ten targeted security regressions; fixes are documented in SECURITY_REVIEW.md.

Ruff lint/format, mypy (six production modules), Python compilation and all three JavaScript syntax checks passed. `tests/browser_smoke.py` passed existing desktop discussion flows. `tests/browser_handoffs.py` passed actual Chromium plus three real stdio MCP clients: native task → Web handoff, individual instructions, progress, scoped context/XSS, failure/retry, fan-in, cancelled late reply rejection, delayed-navigation safety, visible errors, Web demo task creation, room isolation and English/Chinese. Browser-generated screenshots/video contain synthetic DEMO work only, not real provider accounts.

CI runs both browser scripts and Python 3.12/3.13 checks. A local result is not a remote CI result; the published commit's Actions run is the source of truth. Main is not merged as part of this feature review.

真实 Grok/dot/DS Bot 联调未执行。dot hosted plugin 的 OAuth 2.1 接线尚未实现，当前静态 Bearer 网关不能宣称兼容；没有部署、持久账号凭据或自动 wake。新任务仅支持活跃 Bot 主动读取、领取与回报，入口活跃轮询汇总。没有 CLI runner 或模型替身。桌面优先，未新增移动端验收。

## Desktop reference correction — current branch / 当前分支

2026-10-31: ruff lint/format, mypy (5 modules), Python compilation, JS syntax and 41 unit/MCP/security tests passed with `requirements.lock` in a local Python 3.12 venv. Static DOM references resolve (70 unique IDs, 65 JS references). Independent source review found polling focus, budget-validation and dialog-label issues; these were corrected.

Independent cloud QA materialized the exact eight changed files from remote commit `59bda253bb356f95b8d647dedc4d0567f7a28602`; its local Git tree matched `95730e4876d2aa2b95aaa97ddc873ef43da17435` before testing. This executor can run Chromium. The full 41-test suite, Ruff lint/format, mypy, Python compilation, JS syntax and actual desktop browser flows passed. CI exposed a refresh race: a mutation refresh could be skipped while polling was active, leaving stale membership displayed. Mutation reads now force refresh; a generation guard prevents an older polling response overwriting the newest state. A browser regression explicitly holds an old poll across a room-settings mutation. The first review CI browser run failed before this correction; final success is commit-specific.

Browser coverage includes EN/ZH, two-column layout, right black user bubbles/left gray bot bubbles, group creation and selection, search without navigation, bounded demo Lead, membership registration/removal, waiting/stop, history, XSS-as-text, options and management dialogs, Escape/close/focus restoration, repeated opening/closing, invalid budgets 0/21/1.5 (no run queued), secret clearing and language-only persistence. Screenshots at 1280×900 show the complete desktop shell and composer, EN/ZH and management, using only synthetic demo data. All screenshots were visually inspected for sensitive values; no credentials appear.

This confirms desktop functional behavior, not fidelity acceptance against Grok: final pixel comparison is performed by the parent task/user. Mobile design/acceptance remains deferred; no mobile checks ran in this pass. No real Grok/DS Bot/dot account, deployment or external provider test was performed. No design skill files are in the product tree.

## Historical verification / 历史验证

Local verification date / 本地验证日期: 2026-10-31.

| Check / 检查 | Result / 结果 |
|---|---|
| `ruff check .` | Passed / 通过 |
| `ruff format --check .` | Passed / 通过 |
| `mypy` | Passed: 4 production Python modules / 4 个生产模块 |
| `python -m unittest discover -s tests -v` | 35 passed / 35 项通过 |
| `python -m compileall -q roundtable.py server.py grok_adapter.py mcp_bridge.py` | Passed / 通过 |
| `node --check static/app.js` and `static/i18n.js` | Passed / 通过 |
| `PYTHONPATH=. python tests/browser_smoke.py` with system Chromium | Passed / 通过 |

The MCP tests launch actual official SDK client/server subprocesses, negotiate initialize, list tools, and call them over stdio. They cover an owner-scoped demo discussion and three independently authenticated MCP clients acting as initiator, Lead, and peer. Tests verify correlated phases/replies, replay deduplication, allowance exhaustion, self-call rejection, cross-room isolation and credential revocation.

MCP 测试运行真实官方 SDK 客户端/服务端协议，不是直接调用 Python 函数冒充 MCP。模拟的是身份与消息，不是声称真实 Grok/dot/DSH 已接入。

Browser coverage: English/Chinese UI, invalid-token error, group creation, Lead selection, separate Lead registration, waiting/stop, member removal, room rename, history selection, second-room isolation, XSS-as-text, mobile width, language persistence and absence of token persistence. No unhandled browser JavaScript errors were observed.

浏览器测试覆盖完整中英文流程；消息原文不随语言切换而翻译。测试数据均为合成内容，未联系真实 Bot、未设置用户持久产品凭据。

Independent review details and reproduced issues are recorded in [SECURITY_REVIEW.md](SECURITY_REVIEW.md). Remote CI is commit-specific; consult the repository Actions run for the published commit rather than treating this local report as a remote CI result.

Review follow-up: persisted membership-bound probe nonce with legacy schema migration; tested cross-room/rejoin isolation and browser display. Added safe local diagnosis stages, bounded callback deadlines, concurrent healthy delivery during slow callbacks, unsubscribe during delivery and verification, and stale receipt rejection. All external callback tests use injected/mocked transport, not vendor accounts.
