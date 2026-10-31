# Bot Roundtable / Bot 圆桌

把不同 bot 的消息放进同一个可控房间：指定参与者、限定回复次数、查看来源、随时停止。

**当前是本地可运行的桥接 MVP，不是已经打通 Grok Bot 与 dot 的产品。** 两个内置 demo bot 是确定性程序，不是模型，也不冒充真实 bot。运行时只依赖 Python 3.12+ 标准库；SQLite 保存房间、讨论、消息与任务。

## 快速开始

```bash
# 在项目根目录执行
export ROUNDTABLE_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python server.py
```

浏览器访问 `http://127.0.0.1:8765`，把自己设置的管理员令牌填入页面，创建房间。安全保存返回的房间 ID 与令牌，选中 demo-planner 和 demo-critic，输入议题并开始。默认最多 4 条 bot 回复，可选 1–20 条。页面的“回复数”是整个讨论的总量，不是每个 bot 的数量。

不需要 API key，不安装模型 SDK，不发出外部请求。`Ctrl+C` 停止服务。数据默认保存在 `data/roundtable.db`；`--db`、`--port` 可更改路径与端口。不要把数据或令牌提交到 Git。页面不使用 localStorage；刷新后重新填写房间 ID / 令牌。

## 实际接入能力

| 接入对象 | 已实现 | 验证状态 / 限制 |
| --- | --- | --- |
| 两个 demo bot | 自动轮流对话、来源标记 | 核心测试 + 浏览器实测通过；不是真实 AI |
| 通用 bot / 自建 agent | 按房间和 agent 隔离的 HTTP polling mailbox + reply webhook | 本机 HTTP 集成测试通过；需要用户编写或授权桥接程序 |
| Grok Bot routine | 独立 HTTPS Bearer POST 适配器与显式单次 CLI | Mock 验证请求、200 acceptance、不跟随重定向；**未真实联调**，回程需用户配置 |
| dot | 可供 owner 明确发起任务使用的通用 mailbox 协议 | **experimental / manual**；无官方自动 bot-to-dot 入口实现，未联调 |
| Slack / Teams / Grok 群聊 | 未实现 | 不是把现成 bot 加入这些平台的群聊机器人 |

官方依据（核对日期 2026-10-31）：

- [Grok Bot Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations)：routine 创建的 webhook 使用 POST 与 Bearer key；HTTP 200 只表示已接受并启动，结果在 Bot chat。本文适配器不使用另一个 automations HMAC 协议，也没有虚构结果查询 API。
- [OpenAI Manage dots](https://help.openai.com/en/articles/20001554-manage-dots-in-chatgpt-workspaces)：只有 owner 能指挥 dot，其他人的 DM 或 mention 不启动工作。不能假设别的 bot 在 Slack @dot 就能启动它。Owner 可以另行明确授权有限的读取/回复任务；本项目未验证这条路径。

## 通用接入协议

所有写请求使用 JSON。令牌放在 `Authorization: Bearer …`，不放 URL。房间与 agent 的令牌不同；agent 令牌不能管理房间。令牌创建时只返回一次，数据库保存 SHA-256 摘要。

| 方法与路径 | 令牌 | 请求 / 返回 |
| --- | --- | --- |
| `POST /api/rooms` | 管理员 | `{"name":"讨论"}` → `{id,token,name}` |
| `GET /api/rooms/{room}` | 房间 | agents、runs、messages |
| `POST /api/rooms/{room}/agents` | 房间 | `{"id":"my-bot","kind":"mailbox"}` → `{id,token,kind}`；kind 可为 mailbox / grok |
| `POST /api/rooms/{room}/runs` | 房间 | `{"body":"议题","targets":["my-bot","demo-critic"],"budget":4,"request_id":"唯一请求ID"}` |
| `POST /api/rooms/{room}/stop` | 房间 | `{}` |
| `GET /api/rooms/{room}/agents/{agent}/inbox` | 对应 agent | 待处理 job 数组；重复 polling 返回同一 job |
| `POST /api/rooms/{room}/agents/{agent}/reply` | 对应 agent | `{"job_id":"…","body":"回复","failed":false}` |

Job 包含 `id, room, run, deadline, messages`。每条消息只有 `sender, source, body`。只包含**当前房间的当前讨论**，不会夹带旧讨论、会话历史、环境变量或其他房间数据。

桥接程序按 `job.id` 去重，处理一次并回传。相同 job 的相同回复幂等；不同回复返回 409。失败用 `failed:true`，整个讨论结束。默认每条回复等待 60 秒，超时后迟到回调返回 409。房间一次只能有一个运行中的讨论。`targets` 是明确的定向提及与轮流顺序；消息正文里的 `@name`、URL、代码都只是文本，不能变更路由、扩大轮次或执行工具。

## Grok Bot 接线边界

1. 用户在自己的 Grok Bot 创建 routine webhook，确认其操作范围和费用。不要把房间内容当作提升权限的指令。
2. 用房间令牌注册 `kind:grok` 的 agent。Grok agent 仍通过 mailbox 获取任务，服务端不会自动调用它。
3. 在自己的受信运行环境中显式设置 `GROK_ROUTINE_URL`、`GROK_ROUTINE_KEY`、`GROK_ALLOWED_HOST`。最后一个值必须与已核验的 routine URL 主机完全一致。不要把 key 写入仓库或命令历史。
4. 桥接程序把**一个 mailbox job 对象**传给 `python grok_adapter.py --dispatch` 的标准输入。CLI 只输出 accepted/completed/job_id，不输出 key。适配器不自动重试；失败或网络超时可能已触发远端运行，先在 Bot chat 核实。
5. 将结果通过上述 reply 协议回传。关联键是原始 job id；HTTP 200 不是完成消息。用户需要自行在 routine 或受信桥接程序配置回程；这不是官方自带 callback API。

**当前服务仅监听 loopback，外部 Grok 无法直接回调它。** MVP 可由用户运行本地桥接程序读取结果并回传；安全的远程网关、TLS、公开回调地址未实现。不要把服务裸露到公网。适配器只支持直接 TLS 的受信部署；检测到代理环境时明确失败，不绕过代理。云端代理网络中的真实 dispatch 本次未执行。

## 验证

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
mypy
python -m unittest discover -s tests -v
python -m compileall -q roundtable.py server.py grok_adapter.py
node --check static/app.js  # Node 22+，仅开发检查需要
```

可选浏览器验证：安装 `playwright` 与 Chromium，设置 `CHROMIUM_PATH`（默认 `/usr/bin/chromium`），运行 `PYTHONPATH=. python tests/browser_smoke.py`。测试创建房间、4 条示例回复、完成状态、XSS 文本不执行、移动端不横向溢出及无 JS 错误；截图写入忽略的 `artifacts/`。不对真实 bot 发消息。

Python 服务无需前端打包；compileall 和 JS 语法检查是本项目的构建验证。CI 已配置 Python 3.12/3.13 的 lint、typecheck、tests、语法检查。远端 CI 只有在仓库发布后才能验证。

## 安全与已知限制

- 单机开发 MVP，非公网多租户服务。Host/Origin 校验、无 CORS、CSP、纯文本 DOM 渲染、请求大小上限。
- 房间令牌等于房间控制权；agent 令牌只能处理该房间该 agent 的任务。无账户登录、令牌轮换/撤销界面、审计后台、配额或数据加密。删除本地 DB 会清空全部房间，不是撤销单个令牌的方法。
- SQLite 持久化本身不防本机文件读取；启动时新文件使用私有权限。日志只有 job id 与状态，不含消息、URL 或令牌。
- Stop 阻止后续调度与回调入库；无法撤销已经在外部启动的工作。外部 bot 自身的工具、审批、费用必须由其 owner 限制。
- 进程重启把未完成任务标记 interrupted，不自动重放。重试讨论必须由用户发起新的 request_id。
- 适配器固定 operator 配置 URL，拒绝非 HTTPS、私网解析、重定向，连接使用校验过的 IP 并保留 TLS 主机验证。消息内容无法决定外连地址。
- 单进程调度；不支持多副本；消息列表暂未分页。持续大量使用前需补资源配额、保留策略、运维与生产安全评审。

详见 [ARCHITECTURE.md](ARCHITECTURE.md)。MIT License，欢迎提交聚焦单个 adapter 或验证场景的改进。
