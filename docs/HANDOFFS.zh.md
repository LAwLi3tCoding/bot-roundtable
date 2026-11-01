# 原生 Bot 委派与交接

[English](HANDOFFS.en.md) · [快速开始](../README.md)

在 Grok Bot（或另一现成 Bot）里发起委派，通过本项目 MCP 给其他群成员分别下达任务。Web 的“任务与交接”显示同一个 `task_id`、每位执行者的独立指令、进度、结果和失败；入口 Bot 活跃时调用 `get_task` 取回汇总。Hub 不调用模型、不运行编码 CLI，也不自动替 Bot 总结。

## 先在本机跑通

按 README 启动服务器、创建含两个 demo 成员的群，点击“委派任务”。填写标题、共享上下文，并为两个成员分别写指令。提交后可切换“汇总”与各成员交接线程；demo 自动领取并产生带 `[DEMO]` 的确定性文本，验证的是通信流程。

Web 也能查看从原生 MCP 创建的任务，补充共享或单个执行者上下文、重试失败交接、取消任务。补充文字只是数据：不会重新执行已完成任务、增加权限或预算。取消失败任务可阻止其后续重试；取消向所有子任务递归传播，但不能撤回外部 Bot 已产生的副作用。

## 首轮真实组合：Grok Bot + dot

1. 分别注册现成 Grok 和 dot 身份并加入同一群；注册本身不表示已接通。为入口 Bot 授予最小发起额度，保管不同的群成员 token，不能把 admin/room token 给 Bot。
2. 在产品允许的 MCP 设置中连接本项目的 stdio 或认证 Streamable HTTP。云端产品访问不了另一台电脑的 localhost；需要操作者准备可达 HTTPS 地址与客户端支持的认证方式，参见 [HTTP 指南](HTTP.zh.md)。本项目未部署公网，也没有 OAuth 授权服务器。
3. **dot 的直接 MCP 挂载路径及账号联调尚未验证**。必须先由 owner 在 dot 中明确发起限定任务，再确认该环境能使用此连接；没有此能力时应停在“尚未接通”，不能用 CLI 或模型 API 冒充 dot。dot 官方 MCP Events 支持用户先订阅的触发路径，真实账号仍待验证，见 LOCAL.zh.md。
4. 双方活跃且接线验证成功后，入口调用 `create_task`，执行者主动 `receive_assignments` → `claim_assignment` → `report_assignment`，入口 `get_task`。没有读取时显示排队/到期，不伪造回复。MCP 不保证 turn 结束后自动唤醒，入口休眠也不会被本项目自动拉回。

Grok 官方 routine webhook 是潜在可选 wake 路径，200 只代表 accepted。当前 `grok_adapter.py --dispatch --assignment` 增加显式 assignment 通知（不提前领取），仍保留旧 job 协议；没有配置真实 routine、发送请求或验证回程。DS Bot 的独立配置仍见 [DS Bot 指南](DS_BOT.zh.md)，本轮不要求安装。

共享产品 connector 的 token 只证明持有凭据，不证明产品内部多个 Bot 的强身份隔离。请使用产品实际支持的独立配置与最小权限；若无法独立隔离，应将它视为共享主体，不能假称各 Bot 已隔离。

## MCP 工具与一次完整交接

旧讨论的 7 个工具仍保留；新增以下 9 个工具（合计 16）：

| 工具 | 用途 |
|---|---|
| `create_task` | 标题、共享上下文、独立 `{worker,instruction}` 数组、request_id；立即返回 task_id |
| `list_tasks` | 最新 100 个有权查看的任务；不是全量历史分页 |
| `get_task(task_id, after)` | 状态、结构化汇总、增量事件；返回 cursor / has_more |
| `receive_assignments` | 当前身份可领取或正在处理的交接；不会返回他人私有指令 |
| `claim_assignment` | task_id、assignment_id、expected_attempt、request_id；返回短期 lease 与 attempt |
| `report_assignment` | 携带 lease / attempt，报告 progress、completed 或 failed；progress 续租 |
| `add_task_context` | 入口/房间 owner 添加共享或单交接补充，不触发执行 |
| `retry_assignment` | 入口/owner 在剩余预算、额度与尝试次数内重排失败交接 |
| `cancel_task` | 入口/owner 取消任务及子任务 |

示例参数（ID 用自己群里的真实登记值替换；不包含凭据）：

```json
{
  "title": "审核发布方案",
  "context": "仅使用本次提供的计划，给出可执行建议。",
  "assignments": [
    {"worker": "dot-reviewer", "instruction": "找出计划中的遗漏与风险。"},
    {"worker": "another-member", "instruction": "独立检查验收步骤是否充分。"}
  ],
  "budget": 4,
  "timeout_seconds": 600,
  "request_id": "caller-generated-unique-key"
}
```

如果只有 Grok 和 dot 两名成员，Grok 只给 dot 一个 assignment；入口不能给自己排任务。多执行者需要额外真实成员或清楚标记的 demo。入口可同时担任群 Lead，但任务模式不受旧讨论“Lead 不能自行发起”的限制；旧讨论保护仍保留。

执行者收到 assignment 后，以其当前 `attempt` 作为 `expected_attempt` 领取。保存返回的短期 lease，仅使用本人的身份报告；每次新的语义操作生成新 request_id，网络重试沿用同一 key 和完全相同参数。`get_task` 的 cursor 用于增量事件，`has_more` 为真时继续读取。任务内所有 assignment 完成才算 completed；某个失败且其余都终结时为 failed。入口可将结构化结果在自己的原生会话中整理给用户，Hub 不生成伪 AI 汇总。

## 数据、权限与恢复

- `tasks` 保存 room、认证来源 origin/coordinator、父/root 关联、深度、预算、deadline；`assignments` 保存独立指令、成员 epoch、状态、attempt、lease 摘要、结果与文本 artifacts；`task_events` 为审计事件；`task_receipts` 为幂等回执。
- 单任务 1–6 个不同执行者，禁止向入口自身排队；一群最多 20 个活跃任务。预算 1–20 次 dispatch；首次分配在创建时预留，重新领取另扣一次。Bot 发起额度同样跨任务累计扣减、不退款，与旧讨论共用。
- lease 默认 60 秒，可选 `lease_seconds` 为 30–1800 秒；progress 按所选时长续租但不越过任务 deadline。每 assignment 最多 3 次领取；超时后在剩余预算内可重新领取，旧 lease 不再有效。任务 deadline 30–86400 秒，默认 600 秒。
- 子任务只允许同一 origin，深度最多 2，与 root 共用预算和截止时间。关联不是 DAG：父任务状态只汇总它自己的 assignments，不自动等待所有子任务。
- origin/房间 owner 可看整个任务；执行者只看本人的指令、结果及共享上下文。其他群、无关成员不能查看。移除再加入会得到新成员 epoch，不能继承旧任务权限。
- 最多 100 条补充上下文；每交接约 60 条事件后拒绝更多 progress，但仍允许最终结果。结果最多 3 个纯文本 artifact（名称 80 字符，正文 2000 字符），不执行内容、不下载 URL。
- 新任务和 lease 会持久化；进程重启不自行运行外部任务，恢复后由执行者检查状态/续租/重新领取。旧 discussion 重启仍标记 interrupted，与新模式不同。
- 同一身份/成员 epoch/操作/request_id + 相同参数返回原回执；不同参数冲突 409。重放 claim 回执不会续租，可能已失效，调用方应查询状态。凭据只存摘要，**claim 幂等回执含短期 lease 原文**，数据库及备份必须当作敏感数据保护；日志和普通任务查询不输出 lease。
- SQLite 单进程事务串行化 claim/reply/cancel；不承诺外部 exactly-once。任务文本和结果未加密，仍无生产级配额/账户系统。不要将个人原生会话全量转发，只提供明确授权的当前任务信息。

## 共用 HTTP 模型

Owner 路径为 `/api/rooms/{room}/tasks`；Bot 路径为 `/api/rooms/{room}/agents/{agent}/peer/tasks`，均使用各自 Bearer 凭据。GET 列表、POST 基础路径创建；POST `/query`、`/inbox`、`/claim`、`/update`、`/context`、`/retry`、`/cancel` 对应工具。Web 和 MCP 使用同一个存储与事件游标。任何 payload 都不能替换认证身份或扩展群权限。

## dot hosted plugin authentication gate / dot 托管插件认证门槛

[Official authentication guidance](https://developers.openai.com/plugins/build/auth) requires OAuth 2.1 for authenticated hosted MCP plugins; an OAuth access token is not an arbitrary custom static API key. The current static-Bearer gateway does not implement this flow. Follow the [official connection steps](https://developers.openai.com/plugins/deploy/connect-chatgpt) only after compatible HTTPS/OAuth infrastructure exists, install the plugin, then verify actual tool visibility in the owner's active dot task. This remains unverified and blocked on that infrastructure; no fake OAuth compatibility is claimed. Grok also has separately authorized local execution; verify its actual execution host before assuming localhost reachability.

认证 hosted MCP plugin 预期 OAuth 2.1，不能直接把当前静态 token 当作自定义 API key 填入后宣称可用。需先准备兼容 HTTPS/OAuth 接入，再按官方步骤添加/安装 plugin，并在 owner 主动发起的 dot 任务中验证工具可见性。本项目尚未实现或验证这条产品接线路径；Grok 也有单独授权的本机执行能力，应先验证执行位置。

Current local/private integration paths and evidence gates: [中文](LOCAL.zh.md) / [English](LOCAL.en.md). Public hosted-plugin OAuth requirements do not establish or rule out the separately permissioned private tunnel route. 当前公共 OAuth、私有 tunnel 和授权本机 API 是不同接线路径，不能互相冒称已验证。
