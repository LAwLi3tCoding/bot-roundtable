# Verification / 验证记录

## Avatar and motion refinement / 头像与动效细化

Independent QA started from the exact remote `f94c5db2bb2339024896ca0efb78ac56ec3d720b` tree `6161a6fc28f608abd2f40c156f98ce871d591594` (all nine changes fetched via the connector). Existing backend and desktop checks remain required.

Fixes from real Chromium and independent source review: escape the Bot ID HTML-pattern hyphen for modern `v` regex syntax; clear render signatures when disconnected; immediately release detached navigation avatars; normalize bot-initiated identities and keep queued initiation idle rather than falsely finished. No untrusted SVG markup is parsed, and the new static route is a fixed allowlisted filename.

Verification: 41 Python tests, 10 Node avatar/state/observer tests, lint/format/typecheck, Python compilation and JS syntax. Desktop Chromium covers EN/ZH, all existing group/Lead/message flows, stable avatar identities across views, compact animations disabled, visible pending transform changing over time, reduced-motion disabling, closed-dialog/offscreen pausing, and real observer target cleanup/disposal after repeated UI updates. Document-hidden event behavior is additionally unit-tested with simulated visibility events; no physical-device or OS background-window guarantee is inferred.

The recording contains 220 actual browser frames encoded as 22-second 1280×900 VP9 WebM at 10 fps. Ten decoded frames from a steady pending interval had ten distinct hashes, and working/failed video frames were visually inspected. This confirms the deliverable contains changing rendered pixels, not a still image. Demo replies/failure are explicitly test-driven through the real Store task/reply protocol. No external bot account or public deployment is involved. Screenshots and recording contain no visible credentials; only project-original assets are committed. This review branch is not authorization to merge main.

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
