# Verification / 验证记录

## Desktop reference correction — current branch / 当前分支

2026-10-31: ruff lint/format, mypy (5 modules), Python compilation, JS syntax and 41 unit/MCP/security tests passed with `requirements.lock` in a local Python 3.12 venv. Static DOM references resolve (70 unique IDs, 65 JS references). Independent source review found polling focus, budget-validation and dialog-label issues; these were corrected.

Independent cloud QA materialized the exact eight changed files from remote commit `59bda253bb356f95b8d647dedc4d0567f7a28602`; its local Git tree matched `95730e4876d2aa2b95aaa97ddc873ef43da17435` before testing. This executor can run Chromium. The full 41-test suite, Ruff lint/format, mypy, Python compilation, JS syntax and actual desktop browser flows passed. No product-code fixes were needed in this QA pass.

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
