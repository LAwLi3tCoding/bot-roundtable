# Feasibility / 可行性（2026-10-31）

**The local communication core works; native Grok↔dot interoperability is not yet verified. 本机通信核心已验证，但没有真实 Grok↔dot 接通证据。**

The project is a local protocol service with adapters for existing bots. It never automates vendor UI, controls their coding CLIs, or substitutes model APIs. Existing room/task/assignment/event storage remains authoritative. Detailed paths and the minimum real acceptance procedure are in [中文](docs/LOCAL.zh.md) / [English](docs/LOCAL.en.md).

| Capability / 能力 | Implemented / 已实现 | Contract test / 契约验证 | Native account / 真账号 |
|---|---|---|---|
| Rooms, Lead, independent handoffs | Yes; existing core retained | Python + real SDK + Chromium | Not tested |
| Scoped local HTTP client / doctor | Fixed loopback and operation allowlist; evidence levels separated | Real local HTTP requests; no vendor impersonation | Not tested |
| Grok authorized local API path | Client ready; official capability documented | Local client tested | User's computer/permission needed |
| Grok routine assignment hint | Explicit opt-in; no lease claim or automatic retry | Mock outbound contract; prior SSRF tests retained | Routine/key/return path needed |
| dot MCP Events | Opt-in same authenticated HTTP endpoint; signed verification and durable outbox | Real SDK initialization + documented draft RPC + injected callback receiver | Plugin/subscription/callback response needed |
| dot private MCP tunnel | Documented official setup and target-only credential-reference route | No tunnel installed or simulated as successful | Org/workspace access and real discovery needed |
| Public hosted dot plugin | OAuth not implemented | Not claimed | Not supported by static API key alone |
| DS Bot | Existing MCP documentation retained | Protocol only | Not tested |

Corrections to earlier assumptions: Grok can perform separately authorized local execution, including API calls; it is not restricted to cloud-only access. dot has an official user-requested MCP Events trigger path. A plain MCP call still does not wake an idle bot by itself. Desktop-only local plugins do not establish cloud-dot access. Private tunnels are not public plugin distribution and require their own permissions.

Official sources: [Grok computer and apps](https://docs.x.ai/grok-bot/computer-and-apps), [Grok security](https://docs.x.ai/grok-bot/security), [Grok troubleshooting](https://docs.x.ai/grok-bot/troubleshooting), [routine webhook](https://docs.x.ai/grok-bot/skills-routines-and-automations), [MCP Events](https://developers.openai.com/plugins/build/mcp-events), [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), [desktop-only plugins](https://developers.openai.com/plugins/deploy/desktop-only), [hosted-plugin authentication](https://developers.openai.com/plugins/build/auth), [official tunnel local-header configuration](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md), [DS Bot author repository](https://github.com/Fei2411/DS-Bot).

No network protection is disabled for compatibility. This execution environment has no user's local machine or real bot/tunnel authorization. Therefore the outstanding acceptance is explicit: native probe/read → one approved task/result roundtrip → reverse direction → separately approved event wake and unsubscribe. No additional demo can replace these checkpoints. 当前未创建持久账号凭据、未部署公网、未调用真实 routine/callback、未对外派发 Bot 任务。
