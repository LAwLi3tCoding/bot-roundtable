# 本机 Bot 接入：先验证，再启用交接

[English](LOCAL.en.md) · [任务协议](HANDOFFS.zh.md)

目标是用户电脑上的通信服务，由现成 Bot 自己的授权工具访问。这里没有 computer use 接入、厂商编码 CLI 控制或模型 API 替身。**本版尚未达到 Grok＋dot 安装即用的真实验收**；已完成本机协议和事件契约，真实账号步骤如下。

## 能力与证据矩阵（2026-10-31）

| 路径 | 官方能力 | 本项目状态 | 真实账号 |
|---|---|---|---|
| Grok → 本机 HTTP client | 授权本机执行可运行脚本/API calls | 固定 loopback/群/身份的 local_client.py，探针与任务收发已测 | 未验证 |
| Grok → MCP | custom URL / local command；运行位置需确认 | 原有 stdio/认证 HTTP，正式 SDK 测试 | 未验证 |
| 本机 → Grok routine | 用户创建 routine webhook；200 仅 accepted | 显式 job/assignment 适配器，mock 契约通过；不自动发送 | 未验证 |
| dot → 本机 MCP（私有） | Secure MCP Tunnel，需要 org/workspace 权限 | 提供固定成员配置检查路线；未安装或运行 tunnel | 未验证 |
| dot → 本机工具 | 已连接电脑是否可调用此服务需在实际 dot 中验证 | 可复用窄 client；不假定桌面 local thread 就是 cloud dot | 未验证 |
| 本机事件 → dot | 用户先订阅，MCP Events 签名 callback | 默认关闭的 Events 扩展、持久订阅/outbox，SDK HTTP＋mock callback 已测 | 未验证 |
| 公共 dot 插件 | HTTPS＋兼容认证；静态 API key 不是 OAuth | OAuth 未实现；不以私有 tunnel 冒充公共插件分发 | 未支持 |
| DS Bot | 作者文档中的 MCP 配置 | 保留既有指南，本轮不要求安装 | 未验证 |

依据：[Grok 本机与云电脑](https://docs.x.ai/grok-bot/computer-and-apps)、[本机执行安全](https://docs.x.ai/grok-bot/security)、[API calls 排障](https://docs.x.ai/grok-bot/troubleshooting)、[routine webhook](https://docs.x.ai/grok-bot/skills-routines-and-automations)、[MCP Events](https://developers.openai.com/plugins/build/mcp-events)、[私有 tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)、[desktop-only 插件边界](https://developers.openai.com/plugins/deploy/desktop-only)。Grok 的本机执行需单独授权；不能再笼统认为只在云电脑执行。Desktop-only stdio 插件只适用于本地线程，不能证明 cloud dot 接通。

## 1. 本机服务与最小无副作用探针

按 README 安装 Python 依赖、启动 `server.py`，在 Web 注册自己的 Grok/dot 身份并加入一个测试群。各身份使用自己的 agent token，默认不授予任务发起额度。令牌只通过本机安全环境引用配置，不贴进聊天、命令参数、截图或仓库。

客户端沿用 `ROUNDTABLE_URL`（默认 `http://127.0.0.1:8765`）、`ROUNDTABLE_ROOM`、`ROUNDTABLE_AGENT`、`ROUNDTABLE_TOKEN`：

```bash
python local_client.py doctor
python local_client.py probe
```

`probe` 只写一条成员连接观测，不派发任务。返回随机 nonce、room、agent 和时间；Web → 通过 MCP 连接 → 连接证据可看到同一成员最近请求。它证明凭据到达本机服务，不证明真实厂商身份或 Bot 在线。移除再加入后旧观测不继承。

先由你在 **Grok 原生会话**明确要求：只在已授权的本机执行项目的 `local_client.py probe`，使用已安全配置的成员环境引用，返回非秘密的 nonce/room/agent；不读取个人会话、不发任务、不改权限，若只能使用云电脑则报告阻塞。由你确认 Grok 的具体本机执行授权，保持厂商权限检查。不要默认改成 Always allow。

这一步成功的证据必须来自实际 Grok 会话和本机对应观测；我们运行测试 client 不算。

## 2. dot 私有连接 gate

先确认目标 Platform organization、ChatGPT workspace、Tunnel 权限与该 dot 能用的插件。创建/修改 tunnel 需要 Read＋Manage，运行/选择需要 Read＋Use；必须关联正确 workspace。只从官方页面取得客户端，未授权时本项目不安装、不创建 tunnel 或 key。

[官方配置参考](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)支持本地目标专属 `mcp.extra_headers`，值可用环境引用。可审核如下配置片段（不是完整 profile，也未做真实联调）：

```yaml
mcp:
  server_url: http://127.0.0.1:8766/mcp
  extra_headers:
    Authorization: env:ROUNDTABLE_TUNNEL_AUTH_HEADER
```

该环境值由你安全设置为完整的 `Bearer <此 dot 的 agent token>`，不能填管理员/room token。官方客户端 `help quickstart` 与 `doctor --profile <name> --explain` 是配置检查入口；不要用不明安装脚本。HTTP gateway 的 `ROUNDTABLE_HTTP_GRANTS` 仍需明确包含该成员。若云端转发的 Authorization 覆盖本地 header，或产品拒绝此认证配置，记录实际错误并停下，不能关闭认证来凑通。公开 hosted plugin 的 OAuth 路线另行处理。

这是**私有 tunnel＋本地固定身份**候选路径：有权使用该 tunnel 的主体可能共用这一成员身份。限制 tunnel/workspace 使用者，不能把它宣称为每个 dot 的强隔离。Tunnel 不适用于公共插件发布，也不是 Grok 通用隧道。

在 dot 中实际发现并调用 `list_rooms` / `list_bots`，核对唯一群和成员后才算此阶段通过。若使用已连接电脑的本机工具路径，则也必须实际运行 probe；本项目未验证此 dot 产品路径。

## 3. 一个真实交接，再扩展多人

双方读取能力通过后，仅给入口成员 1 次发起额度：Grok 创建一个给 dot 的 assignment，内容仅为双方明确同意的非敏感测试短句，预算 1、截止时间 120 秒。dot 在 owner 明确发起的任务里领取并回报；Grok 取回结果。Web 核对同一 task_id、不同成员、唯一 assignment、完成状态；重发同一 request_id 不产生第二任务。之后反向验证 dot → Grok。测试消息本身的外发仍需你确认目标与内容。

窄客户端操作为 `tasks`、`task`、`inbox`、`create`、`claim`、`report`、`context`、`retry`、`cancel`，写入参数从 stdin JSON 读取；不存在任意 URL、任意 API 路径或 shell 执行功能。字段与 [任务协议](HANDOFFS.zh.md) 相同，`report` 对应 update。lease 是短期能力值，不要转贴聊天。

## 4. 事件唤醒单独验收

详见 [Events 契约与配置](EVENTS.md)。用户必须先明确让 dot 监听本成员 `handoff.available`，或入口监听自己的某个 `task.updated`。订阅由真实客户端提供 callback URL/signing secret，不能凭空生成一个网址假装 dot 入口。先确认事件发现、challenge 回显、2xx 接收，再确认原生 dot 真正开始响应；2xx 不等于任务完成。停止监听后验证 unsubscribe 不再投递。

Grok 的 `grok_adapter.py --dispatch --assignment` 可显式发送一份刚读取的 queued assignment（补充 room 字段）；保留 HTTPS/精确主机批准；直连执行公网 IP 校验，显式代理模式使用可信代理 DNS，详见 [配置指南](DOT_SETUP.zh.md)。payload 中 run 是 task_id，id 是 assignment_id，phase 为 assignment。routine 必须重新读取本机 inbox、确认有效后领取并回报，不能把 webhook 正文当新增权限。没有自动 routine 创建、后台轮询厂商或自动重试外发。

## 当前阻塞与完成标准

本轮执行环境不是用户电脑，未绑定 Grok/dot 账号、tunnel/runtime key、真实 callback 或 routine，因此未尝试真实外发，没有账号成功的证据。需要的最小用户动作是：选择运行电脑；安全配置两个群成员身份；批准 Grok 本机 probe；确认 dot 私有连接/电脑路径与权限；再明确批准一个测试交接。若某 gate 不通过，保留本机诊断和错误阶段，不换成 computer use、编码 CLI 或模型替身。

`doctor` is read-only and reports separate configured, transport_verified, native_roundtrip_verified and wake_verified evidence. The last two remain false without real product acceptance. It prints no tokens, leases, callback URLs or secrets.

`doctor` 只读诊断将已配置、传输已验证、原生回环已验证、唤醒已验证分开；后两项不能由本机持有 token 推断，也不会输出令牌/lease/签名秘密。

探针 nonce 会保存在当前成员身份的观测中，并在 Web 连接证据显示，供与原生 Bot 返回值逐字核对；它不是凭据。成员重新加入不会继承旧 nonce。doctor 安全错误码：`configuration_missing` / `configuration_invalid`、`backend_unreachable`、`authorization_rejected`、`protocol_mismatch`。

领取返回的 lease 仅供本机程序使用。可在权限受限的本机目录（Unix `umask 077`，Windows 使用仅当前用户 ACL）通过 stdin/stdout 管道或私有临时文件连接 claim 与 report；完成后删除临时文件。不要把 claim 输出粘贴到聊天、共享日志或截图；需要返回给原生会话的仅是非秘密任务 ID、进度和结果。
