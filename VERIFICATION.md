# Verification / 验证记录

## Desktop reference correction — current branch / 当前分支

2026-10-31: ruff lint/format, mypy (5 modules), Python compilation, JS syntax and 41 unit/MCP/security tests passed with `requirements.lock` in a local Python 3.12 venv. Static DOM references resolve (70 unique IDs, 65 JS references). Independent source review found polling focus, budget-validation and dialog-label issues; these were corrected.

Desktop browser tests were extended for two-column layout, left/right bubble styles, discussion options, search, dismissal/focus and secret clearing. **Browser launch is blocked in this executor by Chromium `socket() Operation not permitted`; no browser assertions ran and no new screenshots were produced here.** The supported escalation failed before launch. Do not treat the historical browser result below as verification of this branch. Mobile design/acceptance is deferred at the user’s request. No deployment or real-provider integration was performed.

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
