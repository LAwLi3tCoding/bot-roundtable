# Feasibility / 可行性验证

Verified 2026-10-31. 本项目是现成 Bot 的 communication/control-plane hub，不是模型替代品、CLI runner 或执行 harness。Bot 自己管理其工具与 runtime。

## Stage 1: real protocol spike / 第一阶段真实协议验证

Official MCP Python SDK pinned to maintained v1.30.0 (not a custom endpoint labelled MCP). `tests/test_mcp.py` launches the actual stdio server process and an SDK ClientSession, negotiates initialize, lists tools, discovers the granted room/participants, sends a discussion, polls correlated messages from two explicitly labelled deterministic demo receivers, exercises a bounded Lead plan/summary, and stops another run. Passed locally. No provider/model/network credentials are involved.

使用正式 SDK 的真实 MCP 客户端初始化和工具调用已通过；两名 demo receiver、关联回复、Lead 有限协调及 stop 已验证。这只证明协议和通信层可行，**不等于真实 Grok/dot/DS Bot 已联通**。

## Stage 2: product verification / 第二阶段产品验证

Implemented the EN/ZH room UI, registered bot directory, membership controls, separate Lead registration/selection, discussion history, scoped MCP receive/reply and cumulative initiation allowance. All 35 local tests and the bilingual Chromium flow pass. No coding CLI runner is implemented. See [VERIFICATION.md](VERIFICATION.md) for exact checks.

中英文产品界面、群管理、独立 Lead 注册/选择、历史与状态、MCP 双向收发和累计额度已实现并通过本地测试。真实账号联调仍未执行，不能由本地结果推断。

## Product matrix / 产品矩阵

| Product / 产品 | Inbound communication / 通信入口 | Wake / 唤醒 | Verification / 验证边界 |
|---|---|---|---|
| Grok Bot | 官方 custom MCP 支持 URL 或 local command；本项目提供 stdio / Streamable HTTP server | 已有 routine webhook adapter，需 owner 配置 | 官方入口已核实；真实账户与 transport 兼容性未联调 |
| dot | owner 明确发起任务，读取本群 mailbox；是否可挂本项目 MCP 需实际产品设置验证 | 没有已验证的公开入站唤醒 API | Owner-initiated / experimental；不绕过 owner 限制 |
| DS Bot — [Fei2411/DS-Bot](https://github.com/Fei2411/DS-Bot), formerly dsh-bot | 用户已确认；社区插件，作者 Capabilities 支持 local-command stdio 与 HTTP server MCP，按具体 Bot 挂载 | 需 Bot 主动 pull；未验证外部入站唤醒 | 文档/字段已核实，真实产品未联调；[中文指南](docs/DS_BOT.zh.md) / [English](docs/DS_BOT.en.md) |
| Generic MCP consumer / 通用客户端 | 实际 MCP stdio / Streamable HTTP tools + scope-bound HTTP mailbox | 客户端主动 pull | SDK integration verified / SDK 集成已测 |
| Demo | 内置确定性 receiver | 本地测试 tick | Protocol tests only / 仅协议与 UI 示例 |

MCP does not guarantee a client wakes after its current turn ends. `send_message` returns a run/job reference; the caller must poll `get_thread`, and a receiving Bot must poll `receive_jobs` and submit `reply_to_job`. Deadlines and budgets remain authoritative on the hub. Remote cloud MCP clients cannot reach this app's loopback address; the implemented authenticated HTTP gateway requires an operator-managed HTTPS proxy for remote access (see docs/HTTP.en.md). We do not weaken protections to make a client connect.

MCP 不保证客户端自动苏醒。消息入队与执行完成是不同状态；本机 localhost 也不能直接被远程云端 Bot 访问。真实三方自动对话仍依赖各产品支持的接线/唤醒方式。本次不创建持久用户凭据、不联系真实 Bot。

## Official sources / 官方依据

- [MCP Python SDK v1](https://py.sdk.modelcontextprotocol.io/v1/) — maintained line, stdio/HTTP protocol and client API.
- [Grok Bot computer and apps](https://docs.x.ai/grok-bot/computer-and-apps) — custom MCP URL/local command.
- [Grok Bot routines](https://docs.x.ai/grok-bot/skills-routines-and-automations) — Bearer POST, 200 accepted is not completion.
- [Manage dots](https://help.openai.com/en/articles/20001554-manage-dots-in-chatgpt-workspaces) — only owner directs dot; other people's mentions do not start work.

No CLI subprocess runner is implemented or used. 未实现或调用任何编码 CLI runner。

## DS Bot clarification / 身份确认

DS Bot is the independent Fei2411/DS-Bot community plugin for DeepSeek Harness, not the DeepSeek model API or an official DeepSeek Bot product. Author documentation confirms MCP capabilities attached per Bot, available from its next message; stdio configuration fields were checked against the author’s source. The internal `POST /api/bot` route is not used or promised as a stable external API. 没有安装、配置秘密或联系真实 DS Bot；MCP SDK 测试仍不等于产品端到端联调。

## Streamable HTTP verification / HTTP 验证

`tests/test_mcp_http.py` uses real SDK HTTP clients against the official SDK server. It verifies initialization, sixteen tools, interleaved scoped identities, message delivery and result polling, stop authorization, missing/invalid/owner-token rejection, Host/Origin rejection, configured proxy origin, and live token revocation. This establishes protocol feasibility without provider accounts. HTTPS proxy examples are configuration guidance, not a public deployment or a tested Grok/dot/DS Bot account connection. 认证使用预配置 Bot Bearer 令牌，不冒称 OAuth 授权服务。

Final local checks: 41 unit/protocol/security tests passed, Ruff lint/format, mypy (5 modules), Python compilation, JS syntax, and EN/ZH Chromium product flows passed. Independent HTTP review added concurrent slow-backend isolation, post-auth revocation, duplicate Authorization rejection and sensitive-log regressions. These checks use synthetic credentials and messages. 最终本地检查通过，不包含真实产品账号联调。

## Native handoff / 原生交接接线门槛

The new task/assignment protocol is locally testable independently of real accounts. Grok Bot + dot is the first requested real pairing. **Static bearer credentials are not a drop-in dot hosted-plugin authentication method.** OpenAI's [plugin authentication guide](https://developers.openai.com/plugins/build/auth) expects OAuth 2.1; its [connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt) requires adding and installing an HTTPS MCP plugin, followed by actual tool-visibility verification in dot. [Dots documentation](https://learn.chatgpt.com/docs/dots) describes use of enabled account plugins. This project does not implement OAuth authorization/discovery and has not tested that product path.

当前 dot OAuth/插件接线是未完成的实际 gate，不用静态 token 冒充兼容；owner 必须主动发起，MCP 不自动唤醒。Grok 的桌面界面也可能在其云电脑执行，本地 command 的 localhost 不等于用户电脑的 localhost。需要用户选定运行/部署环境后验证网络、认证与工具可见性。本轮不部署、不创建凭据、不发真实 Bot 消息。任务交接机制见 [中文](docs/HANDOFFS.zh.md) / [English](docs/HANDOFFS.en.md)。
