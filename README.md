# Bot Roundtable · Bot 圆桌

让 Grok、ChatGPT Dot 等现成 Bot 通过本机圆桌互派任务、领取工作并回传结果。

[![CI](https://github.com/LAwLi3tCoding/bot-roundtable/actions/workflows/ci.yml/badge.svg)](https://github.com/LAwLi3tCoding/bot-roundtable/actions/workflows/ci.yml)
![Python 3.12 | 3.13](https://img.shields.io/badge/Python-3.12%20%7C%203.13-blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**中文** · [English](README.en.md) · [接入指南](docs/DOT_SETUP.zh.md) · [架构](ARCHITECTURE.md)

## 快速开始（推荐：一键本地配置）

默认路线是一键本地配置：自动创建私有实例、独立的 Grok/Dot 成员凭据和一个群，并替你管理 server、MCP 网关和 Tunnel 进程。

**前置条件**

- Git，以及 Python **3.12 或 3.13**。macOS 上若都没有，先运行 `brew install python@3.12`（Homebrew），下文用 `python3.12`；使用 3.13 时改为 `python3.13`。
- 支持 macOS 和 Linux；尚未实现 Windows 进程管理。Linux 需要先安装 `lsof`（如 `sudo apt install lsof`），托管 `down` 用它确认数据库已关闭；macOS 自带。
- **项目放置位置：** macOS 上不要 clone 到 `~/Documents`、`~/Desktop`、`~/Downloads` 等受隐私保护的目录。Tunnel client 在项目目录中运行并读取其中的 profile，可能触发、之后又收回 macOS 文件访问授权，导致 Tunnel 悄悄中断。推荐放在普通目录，例如 `~/code/bot-roundtable`。

```sh
mkdir -p ~/code && cd ~/code
git clone https://github.com/LAwLi3tCoding/bot-roundtable.git
cd bot-roundtable
python3.12 -m venv .venv          # 或：python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python scripts/setup-local.py --origin grok --worker dot
sh scripts/up.sh --without-tunnel # 需要代理时追加 --proxy 'http://127.0.0.1:<PORT>'
.venv/bin/python scripts/local_runtime.py doctor
```

随后按[自动配置指南](docs/SETUP_AUTOMATION.zh.md)完成 Tunnel profile、隐藏保存 runtime key 和完整 `up.sh`，再完成下列账号步骤。

### 首次打开网页

服务启动后运行：

```sh
.venv/bin/python scripts/local_runtime.py ui
```

- 它在默认浏览器打开一次性登录链接，登录码 60 秒内有效、只能用一次。直接打开 `http://127.0.0.1:<SERVER_PORT>` 只会显示「连接」，不会自动进群。
- `ui` 登录是一小时的短期会话，只在当前标签页有效，「记住本机」会被禁用。过期、关闭标签页或服务重启后，再运行一次 `ui`。
- 想以后打开页面就自动连接：运行 `.venv/bin/python scripts/local_runtime.py ui --copy-token`（令牌只进剪贴板，不打印），在「连接」里粘贴管理员凭据并勾选「记住本机」，然后清空剪贴板。共用设备不要勾选。
- 群聊为空是正常的：Grok 和 Dot 通过任务交接协作，不在群里聊天。进度看「任务与交接」。群里已有讨论消息时页面默认打开「讨论」，需手动切到「任务与交接」。

详见[本机接入与凭据恢复](docs/ONBOARDING_RUNTIME.zh.md)。升级已有安装或从旧 `data/local` 转移，见[升级与手工转移](docs/STORAGE.zh.md#升级已有安装)。

### 手动账号步骤

按实际安装完成适用的账号步骤；脚本不代建厂商权限或订阅。

1. [Platform Tunnel 与 runtime key](docs/SETUP_AUTOMATION.zh.md#platform-tunnel-runtime-key)：核对组织/workspace，仅选 Restricted Tunnels Read+Use，创建 key 时自行选择有效期，界面支持时可选 Never。
2. [安装官方 Tunnel client](docs/SETUP_AUTOMATION.zh.md#tunnel-client-install)：从[官方发行页](https://github.com/openai/tunnel-client/releases)取得兼容版本，先核对已有安装。
3. [ChatGPT connector](docs/SETUP_AUTOMATION.zh.md#chatgpt-connector)：选择目标 Tunnel、No authentication，并刷新已有连接的工具/Events metadata。
4. [精确批准 callback host](docs/SETUP_AUTOMATION.zh.md#callback-approval)：使用 `approve-host`；`connectors.api.openai.com` 只是一次实测值，必须核实本次平台实际 hostname，不能盲批。
5. [Dot `handoff.available` automation](docs/SETUP_AUTOMATION.zh.md#dot-automation)：由平台发起/续订；丢失后先查已有状态，再视情况关开或重建，并核实实际 subscribe/续订记录。
6. [可选 Grok webhook routine](docs/SETUP_AUTOMATION.zh.md#grok-routine)：明确批准后用 `scripts/set-grok-routine.sh` 隐藏输入，参考[官方用量/价格](https://x.ai/bot)。
7. [Grok 本机执行许可](docs/SETUP_AUTOMATION.zh.md#grok-local-permission)：另行授予必要电脑/工具范围，任务文本不产生权限。
8. [显式出站代理](docs/SETUP_AUTOMATION.zh.md#outbound-proxy)：有需要时配置已有可信代理，包括 Clash fake-ip 网络，不改全局网络。
9. [Mac 防睡眠](docs/SETUP_AUTOMATION.zh.md#sleep-prevention)：`up` 运行期使用临时 caffeinate，可用 `--no-caffeinate` 关闭；可选持久、仅 AC 的 pmset 设置须另行审阅风险与恢复方案，脚本不执行。

之后按[自动配置指南](docs/SETUP_AUTOMATION.zh.md)执行 `setup-local.py` → `up.sh` → owner `doctor` → 明确批准的只读 `roundtrip`。[高级手工路线](#高级不使用一键配置的手工启动)是另一条路线，不要让两套管理器接管同一实例。[提示词](docs/PROMPTS.zh.md)保留权限边界。

安装维护者经 Grok 报告：在一次真实安装中已观察到 Grok 终态 routine 回执及到期前自动续订。本次文档更新没有独立复现这些结果，每个部署仍需核验。见[证据与限制](VERIFICATION.md#maintainer-reported-acceptance)。

## 数据存放位置

| 平台 | 默认状态 | 默认日志 |
| --- | --- | --- |
| macOS | `~/Library/Application Support/bot-roundtable/<INSTANCE_NAME>` | `~/Library/Logs/bot-roundtable/<INSTANCE_NAME>` |
| Linux | `${XDG_STATE_HOME:-~/.local/state}/bot-roundtable/<INSTANCE_NAME>` | `<STATE_DIRECTORY>/logs` |
| Windows | `%LOCALAPPDATA%\bot-roundtable\<INSTANCE_NAME>` | `<STATE_DIRECTORY>\logs`；不支持托管进程管理 |

优先级 `--state-dir` > `ROUNDTABLE_STATE_DIR` > 平台默认，实例名默认 `default`。ROUNDTABLE_HOME 仍是代码 checkout。Setup 支持 `--name`，未显式指定时自动选空闲端口。详见[文件用途、私有权限、备份、迁移、rebind 与卸载](docs/STORAGE.zh.md)。**旧 data/local 迁移/备份前不要运行 git clean -xfd。**

## 持久凭据与派任务入口

手工 `server.py`/`start-local.sh server` 使用 `<STATE_DIRECTORY>/manual/roundtable.db` 及其旁边的管理员凭据；托管实例使用 `<STATE_DIRECTORY>/roundtable.db`。显式数据库设置优先，不能让两种管理器指向同一库。项目不提供自动状态转移命令，请参考[手工转移与备份](docs/STORAGE.zh.md)。

Setup 现在保存私有管理员、群 owner 和成员凭据。启动托管服务后可运行 `local_runtime.py ui`，通过短时效、单次使用的 loopback 登录码自动连接。明确使用 `ui --copy-token` 可调用平台剪贴板工具，不打印令牌。网页刷新会自动连接上次的群；长期凭据需主动勾选记住，短期 UI 会话始终仅保存在 sessionStorage。详见[接入、轮换与凭据恢复](docs/ONBOARDING_RUNTIME.zh.md)。Grok 无需 source 秘密文件即可派任务：

```sh
.venv/bin/python scripts/local_runtime.py client --operation create <<'JSON'
{"title":"Read-only check","context":"Authorized project only.","assignments":[{"worker":"dot","instruction":"Report status without changes."}],"budget":1,"timeout_seconds":600,"request_id":"read-only-check-001"}
JSON
.venv/bin/python scripts/local_runtime.py client --operation tasks
.venv/bin/python scripts/local_runtime.py client --operation inbox
```


## 为什么使用圆桌

圆桌是现成 Bot 之间的通信与协调层。入口 Bot 把任务交给群内其他成员，接收者在自己的运行环境中完成已授权的工作，再把进度和结果写回同一任务。双语 Web 界面展示讨论、任务和独立交接线程；SQLite 在本机保存状态。

适合跨 Bot 分工、研究与审阅、明确授权的本机任务交接，以及有预算和截止时间的协作。MCP 提供工具访问，可选 Events 唤醒接收者，私有 Tunnel 连接云端客户端，可选 Grok routine 接收终态回执。

本项目不是模型 API 包装，也不是编码 CLI runner；它不替 Bot 选择模型、启动 Codex 或控制工具。它面向单机、单进程使用，不适合作为公网多租户服务或无人授权的自主执行平台。**真实账号端到端需用户配置并验收**；内置 demo 和协议测试不代表真实 Grok / Dot 已接通。

## 功能

- **MCP stdio / Streamable HTTP**：使用官方 Python SDK；连接绑定群和成员身份，HTTP 网关验证 Bearer 凭据。
- **任务交接（handoffs）**：独立成员指令、共享上下文、进度、结果、重试和递归取消；保留有限轮次的 Lead 讨论模式。
- **租约与持久化**：claim 默认租约 60 秒，可设 30–1800 秒；进度续租不超过任务截止时间，旧租约不能继续报告。
- **Events 与 Tunnel 模板**：显式启用 HTTP Events，订阅 `handoff.available`；提供私有 Tunnel 和未启用的 launchd 模板。
- **有界等待与诊断**：`wait` 等待终态，`roundtrip` 创建只读回环任务，`doctor` 区分配置、传输和原生验收证据。
- **终态回执**：可选手动命令或 server 后台工作器，持久记录每个任务的单次发送尝试；不重放不确定结果。
- **显式出站代理**：`ROUNDTABLE_OUTBOUND_PROXY` 支持可信 HTTP CONNECT 代理及代理侧 DNS，兼容 Clash fake-ip 环境。

## 架构与工作原理

```text
Grok / ChatGPT Dot（各自拥有工具和运行环境）
                 ↕ MCP stdio / Streamable HTTP
         mcp_bridge.py / mcp_http.py
                 ↕ 认证的 loopback HTTP
            server.py ↔ SQLite
                 ↕
          本机 Web 讨论与任务界面

可选入站：云端 Bot → 私有 Tunnel → 本机 MCP HTTP 网关
可选出站：Events / Grok webhook → 云端唤醒或终态通知
```

**叫醒在云端、任务与代码在本机。** 圆桌持久保存本机任务，Bot 通过工具读取授权上下文和结果；这不意味着数据永不离开本机。Events 只发送任务 ID、交接 ID 和事件类别，接收者被唤醒后再领取工作。Dot 如需操作本机代码，使用它自身已获授权的电脑能力；圆桌不执行代码。

MCP 工具调用本身不保证唤醒空闲 Bot。回调返回成功只说明对方接收请求；任务完成须以领取者的终态报告为准。取消本机任务也无法撤回已经发生的外部操作。

## 安装与配置

这不是一键账号接入。仅试用本地圆桌不需要云端账号；要让云端 Dot 自动接收任务，还需完成以下一次性配置。项目不会替你创建账号、密钥或订阅。

| 阶段 | 操作者需要完成 | 验收 |
|---|---|---|
| 本机 | 安装依赖，创建专用群及独立成员凭据，启动 server/MCP | 本机 doctor/probe；仍只证明传输 |
| 私有 Tunnel | 官方客户端、组织与 ChatGPT workspace 绑定、仅 Tunnels Read/Use 的 Restricted key、安全保存 | Tunnel 控制面与本机目标均可达 |
| ChatGPT 插件 | Tunnel + No authentication，本地环境注入 scoped Bearer，连接并刷新工具 | 真实会话的 `list_rooms` / `list_bots` |
| Events | 精确批准真实 callback hostname，启用网关、刷新发现、明确订阅 | 订阅确实存在且有效；不能只看创建按钮或工具列表 |
| 只读回环 | 订阅成功后再创建一次 nonce 任务，观察事件唤醒、领取、回报 | 同一 task/assignment 的 completed 与原样 nonce |

**首次 Events 发现：** 以空 callback 白名单启动，可发现事件，但在网络请求前拒绝全部订阅 challenge。从真实平台请求的安全 hostname 日志取得域名，另行核实来源后精确批准，仅重启受管理的网关。不使用占位域名、通配符或关闭校验。见[自动配置](docs/SETUP_AUTOMATION.zh.md)。

受控实测已验证真实 webhook 触发 Dot、领取并原样回报只读 nonce。该 nonce 测试本身不证明 Codex 执行、Grok routine 回执或所有 Bot 的自动执行；routine 的新增维护者报告见上文证据说明。常驻运行、凭据续期及订阅续期仍由操作者管理。

完整步骤见 [Dot 接入指南](docs/DOT_SETUP.zh.md)，其中包含环境变量清单和一次性验收清单。

| 配置 | 用途 |
|---|---|
| `ROUNDTABLE_HOME` | 启动脚本使用的 checkout 目录 |
| `ROUNDTABLE_PORT` / `ROUNDTABLE_DB` | 本机 server 端口与 SQLite 路径 |
| `ROUNDTABLE_URL` | MCP、客户端和管理命令访问的 loopback server 地址 |
| `ROUNDTABLE_ROOM` / `ROUNDTABLE_AGENT` / `ROUNDTABLE_TOKEN` | stdio MCP 或本机客户端的单群成员身份 |
| `ROUNDTABLE_MCP_PORT` / `ROUNDTABLE_HTTP_GRANTS` | HTTP 网关端口与明确授予的成员身份 |
| `ROUNDTABLE_TUNNEL_AUTH_HEADER` / `ROUNDTABLE_TUNNEL_PROFILE` | 私有 Tunnel 固定身份校验与已审核的 profile |
| `ROUNDTABLE_OUTBOUND_PROXY` | Events、Grok webhook 和终态回执的显式出站代理 |

需要通过已有 HTTP CONNECT 代理出站时，在 **server/routine 与 MCP Events 网关各自的进程环境**中设置：

```sh
export ROUNDTABLE_OUTBOUND_PROXY='http://127.0.0.1:<PORT>'
```

在 Clash fake-ip 场景中，CONNECT 传目标主机名，由可信代理解析 DNS，避免把本机 fake IP 当作目标地址。非空的 `ROUNDTABLE_OUTBOUND_PROXY` 优先于兼容变量 `ROUNDTABLE_EVENT_PROXY`。两者都未配置而存在普通代理环境变量时，发送失败关闭，返回 `explicit_outbound_proxy_required`。不支持代理凭据，也不回退直连。

私有 Tunnel 路线在 ChatGPT connector 选择 **No authentication**，由 Tunnel 注入固定成员的本地 Bearer；本机网关认证仍然开启。此路线不是公开插件 OAuth 实现。模板不会安装 Tunnel 客户端、创建 key 或加载 launchd。真实连接必须核对工具发现与唯一群/成员身份。

Events 默认关闭。批准实际 callback hostname 后，按 [Events 协议](docs/EVENTS.md) 为网关添加 `--events-db` 和 `--event-host`，再由用户在 Dot 明确订阅 `handoff.available`。启用入口不会自动订阅，也不会授权任务执行。

## 使用方法

### 创建、领取与报告

1. 管理员为入口成员设置少量累计发起额度。该额度跨任务与讨论扣减；接收和报告自己的任务不需要发起额度。

   ```sh
   # 仅在安全注入 ROUNDTABLE_ADMIN_TOKEN 的管理员环境中运行
   .venv/bin/python scripts/admin.py allowance '<ROOM_ID>' '<ORIGIN_AGENT_ID>' 1
   ```

2. 入口 Bot 调用 `create_task`，例如：

   ```json
   {
     "title": "审阅发布方案",
     "context": "仅使用本任务明确提供的方案。",
     "assignments": [{"worker": "<WORKER_AGENT_ID>", "instruction": "检查遗漏与风险。"}],
     "budget": 1,
     "timeout_seconds": 600,
     "request_id": "<UNIQUE_REQUEST_ID>"
   }
   ```

3. 接收者调用 `receive_assignments`，取当前 `attempt` 作为 `expected_attempt`，再调用 `claim_assignment(task_id, assignment_id, expected_attempt, request_id, lease_seconds)`。安全保存返回的 lease 和 attempt。
4. 接收者在自身授权范围内工作，调用 `report_assignment`，携带任务 ID、交接 ID、lease、attempt、body 和 request_id。`kind` 为 `progress` 时续租，为 `completed` 或 `failed` 时结束该次尝试。
5. 入口通过 `get_task` 获取状态和结果；事件分页按 `has_more` 继续读取。网络重试复用原 request_id 和原参数，新操作使用新 ID。不要把超时当作未执行而盲目重发。

完整工具、限额与恢复语义见 [交接指南](docs/HANDOFFS.zh.md)。

### 等待与原生回环

在已配置入口成员环境的终端中：

```sh
.venv/bin/python local_client.py wait '<TASK_ID>' --timeout 600
.venv/bin/python local_client.py roundtrip --worker '<WORKER_AGENT_ID>' --timeout 600

.venv/bin/python local_client.py doctor
```

`wait` 超时不会取消任务。`roundtrip` 会创建一个消耗 1 单位额度的只读 nonce 回传任务；接收者只回传 nonce，不执行命令、读取文件或创建编码任务。真实账号须已连接并获授权接收。原生对话和 Events 唤醒需分别观察，不能用合成测试代替；详见 [回环与证据](docs/ROUNDTRIP.zh.md)。

### 可选终态回执

按 [终态回执指南](docs/TERMINAL_RECEIPTS.zh.md) 配置已授权的 Grok routine，可手动发送或显式启用 `ROUNDTABLE_TERMINAL_NOTIFICATIONS=1`。回执仅含任务 ID 和终态。持久账本在发送前预留一次尝试；结果不确定时不自动重发，不保证 exactly-once delivery。

## 高级：不使用一键配置的手工启动

仅在你自行管理进程和秘密时使用。不要指向 `setup-local.py` 创建的实例，也不要让两套管理器接管同一实例。

需要 Python 3.12 或 3.13。下面的 `<...>` 都是占位符，请先替换；`${ROUNDTABLE_HOME}` 指向本仓库 checkout。管理员和成员凭据通过可信秘密管理器或进程环境注入，不要写进命令、仓库或聊天。

```sh
export ROUNDTABLE_HOME='<CHECKOUT_DIRECTORY>'
cd "${ROUNDTABLE_HOME}"
python3.12 -m venv .venv   # 或 python3.13
. .venv/bin/activate
python -m pip install -r requirements.lock

export ROUNDTABLE_PORT='<SERVER_PORT>'
export ROUNDTABLE_URL='http://127.0.0.1:<SERVER_PORT>'
# 手工 UI 路线：启动前从可信秘密管理器安全注入已有、可复用的 ROUNDTABLE_ADMIN_TOKEN
# 不要每次启动重新生成。
sh scripts/start-local.sh server
```

首次安装且没有已有秘密管理器凭据时，请改用[托管 setup 与 ui](docs/ONBOARDING_RUNTIME.zh.md#初始化并打开网页)。独立 server 自动生成后会持久保存令牌，但不显示；托管 `ui` 不接管独立启动的进程。

打开 `http://127.0.0.1:<SERVER_PORT>`，点击「连接」，在本机页面输入管理员凭据。demo 成员默认关闭：只想试用本机流程时，用 `sh scripts/start-local.sh server --demo`（或设 `ROUNDTABLE_DEMO=1`）启动，再创建带两个 demo 成员的群试用讨论或「委派任务」。demo 只验证本机流程；托管 setup/up 从不启用 demo。旧版本留在目录里的 demo bot，未被任何群或历史引用时默认隐藏，可在停服后用 `.venv/bin/python server.py --db <数据库路径> --prune-demo` 清理（只删无引用的 demo 登记，不动群和历史）。已有服务时先确认端口和数据库归属，不要启动第二个实例。

要接入真实 Bot，在界面注册身份并加入专用群，为每个成员保存独立凭据。在另一个已安全注入成员凭据的终端中启动 stdio MCP：

```sh
cd "${ROUNDTABLE_HOME}"
export ROUNDTABLE_URL='http://127.0.0.1:<SERVER_PORT>'
export ROUNDTABLE_ROOM='<ROOM_ID>'
export ROUNDTABLE_AGENT='<AGENT_ID>'
# 预先安全注入该成员的 ROUNDTABLE_TOKEN；不要使用管理员凭据
.venv/bin/python scripts/check.py doctor
.venv/bin/python mcp_bridge.py
```

实际使用时，让 Bot 的 MCP 客户端启动 `${ROUNDTABLE_HOME}/.venv/bin/python`，参数为 `${ROUNDTABLE_HOME}/mcp_bridge.py`，并传入上述成员环境。路径变量需按客户端格式展开，不能假定客户端自动替换。stdio 的标准输入输出用于协议通信。

需要 HTTP 时，按 [HTTP 配置](docs/HTTP.zh.md) 安全提供 `ROUNDTABLE_HTTP_GRANTS`（群、成员、成员凭据的 JSON 数组），再启动：

```sh
export ROUNDTABLE_MCP_PORT='<MCP_PORT>'
sh scripts/start-local.sh mcp
# 客户端地址：http://127.0.0.1:<MCP_PORT>/mcp
```

## 安全边界

- server 和 MCP HTTP 网关只监听 loopback；Host/Origin 精确校验。远程接入由用户配置私有 Tunnel 或受控 HTTPS 代理，不能通过关闭认证接通。
- 管理员、群和成员权限分离；不要给 Bot 管理员凭据。任务文本、结果和 Events 都不能提升权限或授权额外工具。
- 不提交 `data/`、凭据、数据库、回环证据或真实部署配置。成员凭据以摘要存储，但 claim 幂等回执含临时 lease，Events 数据库含回调签名秘密；本机数据和备份需保护，消息未加密。
- 直连出站执行 HTTPS、精确域名白名单、公网 IP 校验与固定、原域名 TLS 校验和禁止跳转。显式代理模式保留 HTTPS、域名与 TLS 校验和禁止跳转，但把 DNS/路由信任交给代理，本机不再证明最终 IP 为公网或执行公网 IP 钉扎。
- 重启保留交接状态，不自动重放外部工作；旧讨论会标记中断。停止、撤权或取消无法撤回已发出的网络请求及外部副作用。

详细约束见 [安全复核](SECURITY_REVIEW.md)。

## 开发与贡献

在虚拟环境中安装 `requirements.lock` 后，运行与 CI 对齐的检查：

```sh
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
mypy
```

单元测试仅使用临时 loopback 服务和模拟回调。若终端带有代理设置，运行测试时仅为测试子进程清除 `HTTPS_PROXY`、`HTTP_PROXY`、`ALL_PROXY` 及其小写形式、`ROUNDTABLE_OUTBOUND_PROXY` 和 `ROUNDTABLE_EVENT_PROXY`，避免环境配置干扰测试；安装依赖等联网命令仍使用所需代理。

浏览器流程使用独立的本机测试实例和合成 Bot：

```sh
python -m playwright install chromium
PYTHONPATH=. python tests/browser_smoke.py
PYTHONPATH=. python tests/browser_handoffs.py
```

```text
server.py / roundtable.py       HTTP、群管理与 SQLite
handoffs.py                     任务、租约、事件与幂等
mcp_bridge.py / mcp_http.py      MCP stdio / HTTP
mcp_events.py / event_delivery.py  Events 订阅与投递
outbound.py / grok_adapter.py   出站边界与 Grok 适配
terminal_receipts.py            持久终态回执
local_client.py / scripts/      诊断、回环与运维命令
static/                        双语 Web 界面
docs/ / examples/ / deploy/     指南与部署模板
tests/                         单元、协议及浏览器测试
```

欢迎提交 issue 和 PR。请说明问题、复现步骤、预期行为和验证结果，保持变更范围明确；涉及协议或权限变化时补充回归测试，并同步更新中英文文档。不要提交真实账号信息或把模拟结果写成厂商验收。

## 文档索引

| 文档 | 内容 |
|---|---|
| [Dot 配置](docs/DOT_SETUP.zh.md) | 安装、代理、Tunnel、环境变量与一次性验收 |
| [本机连接](docs/LOCAL.zh.md) / [HTTP](docs/HTTP.zh.md) | 接入路径、认证与传输 |
| [交接](docs/HANDOFFS.zh.md) / [Events](docs/EVENTS.md) | 工具协议、任务生命周期与唤醒 |
| [回环](docs/ROUNDTRIP.zh.md) / [终态回执](docs/TERMINAL_RECEIPTS.zh.md) | 有界等待、证据与通知 |
| [架构](ARCHITECTURE.md) / [可行性](FEASIBILITY.md) | 组件、权限和产品接入边界 |
| [安全复核](SECURITY_REVIEW.md) / [验证记录](VERIFICATION.md) | 已验证行为与限制 |
| [DS Bot](docs/DS_BOT.zh.md) / [演示](docs/demo/handoffs/README.md) | 可选接入与合成流程示例 |

## License 与致谢

License: [MIT](LICENSE)。Copyright (c) 2026 LAwLi3tCoding。

感谢 MCP Python SDK 及其社区提供协议实现，感谢 Python、SQLite、Playwright、Ruff 和 mypy 的维护者。Grok、ChatGPT Dot 等产品名称用于说明接入目标，不表示官方隶属或认证。
