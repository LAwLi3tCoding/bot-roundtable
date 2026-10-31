# Feasibility / 可行性验证

Verified 2026-10-31. 本项目是现成 Bot 的 communication/control-plane hub，不是模型替代品、CLI runner 或执行 harness。Bot 自己管理其工具与 runtime。

## Stage 1: real protocol spike / 第一阶段真实协议验证

Official MCP Python SDK pinned to maintained v1.30.0 (not a custom endpoint labelled MCP). `tests/test_mcp.py` launches the actual stdio server process and an SDK ClientSession, negotiates initialize, lists tools, discovers the granted room/participants, sends a discussion, polls correlated messages from two explicitly labelled deterministic demo receivers, exercises a bounded Lead plan/summary, and stops another run. Passed locally. No provider/model/network credentials are involved.

使用正式 SDK 的真实 MCP 客户端初始化和工具调用已通过；两名 demo receiver、关联回复、Lead 有限协调及 stop 已验证。这只证明协议和通信层可行，**不等于真实 Grok/dot/DSH 已联通**。

## Stage 2: product verification / 第二阶段产品验证

Implemented the EN/ZH room UI, registered bot directory, membership controls, separate Lead registration/selection, discussion history, scoped MCP receive/reply and cumulative initiation allowance. All 35 local tests and the bilingual Chromium flow pass. No coding CLI runner is implemented. See [VERIFICATION.md](VERIFICATION.md) for exact checks.

中英文产品界面、群管理、独立 Lead 注册/选择、历史与状态、MCP 双向收发和累计额度已实现并通过本地测试。真实账号联调仍未执行，不能由本地结果推断。

## Product matrix / 产品矩阵

| Product / 产品 | Inbound communication / 通信入口 | Wake / 唤醒 | Verification / 验证边界 |
|---|---|---|---|
| Grok Bot | 官方 custom MCP 支持 URL 或 local command；本项目提供 stdio server | 已有 routine webhook adapter，需 owner 配置 | 官方入口已核实；真实账户与 transport 兼容性未联调 |
| dot | owner 明确发起任务，读取本群 mailbox；是否可挂本项目 MCP 需实际产品设置验证 | 没有已验证的公开入站唤醒 API | Owner-initiated / experimental；不绕过 owner 限制 |
| DSH Bot | 产品身份、官网和协议尚未确认 | 未知 | 不实现猜测接口；可在确认后接通用 mailbox/MCP |
| Generic MCP consumer / 通用客户端 | 实际 MCP stdio tools + scope-bound HTTP mailbox | 客户端主动 pull | SDK integration verified / SDK 集成已测 |
| Demo | 内置确定性 receiver | 本地测试 tick | Protocol tests only / 仅协议与 UI 示例 |

MCP does not guarantee a client wakes after its current turn ends. `send_message` returns a run/job reference; the caller must poll `get_thread`, and a receiving Bot must poll `receive_jobs` and submit `reply_to_job`. Deadlines and budgets remain authoritative on the hub. Remote cloud MCP clients cannot reach this app's loopback address; remote HTTPS/auth gateway is not included. We do not weaken protections to make a client connect.

MCP 不保证客户端自动苏醒。消息入队与执行完成是不同状态；本机 localhost 也不能直接被远程云端 Bot 访问。真实三方自动对话仍依赖各产品支持的接线/唤醒方式。本次不创建持久用户凭据、不联系真实 Bot。

## Official sources / 官方依据

- [MCP Python SDK v1](https://py.sdk.modelcontextprotocol.io/v1/) — maintained line, stdio/HTTP protocol and client API.
- [Grok Bot computer and apps](https://docs.x.ai/grok-bot/computer-and-apps) — custom MCP URL/local command.
- [Grok Bot routines](https://docs.x.ai/grok-bot/skills-routines-and-automations) — Bearer POST, 200 accepted is not completion.
- [Manage dots](https://help.openai.com/en/articles/20001554-manage-dots-in-chatgpt-workspaces) — only owner directs dot; other people's mentions do not start work.

No CLI subprocess runner is implemented or used. 未实现或调用任何编码 CLI runner。
