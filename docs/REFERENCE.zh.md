# 参考：任务用法、手工启动、安全与开发

[README](../README.md) 讲的是快速上手。这里保留更细的说明。

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

完整工具、限额与恢复语义见 [交接指南](HANDOFFS.zh.md)。

### 等待与原生回环

在已配置入口成员环境的终端中：

```sh
.venv/bin/python local_client.py wait '<TASK_ID>' --timeout 600
.venv/bin/python local_client.py roundtrip --worker '<WORKER_AGENT_ID>' --timeout 600

.venv/bin/python local_client.py doctor
```

`wait` 超时不会取消任务。`roundtrip` 会创建一个消耗 1 单位额度的只读 nonce 回传任务；接收者只回传 nonce，不执行命令、读取文件或创建编码任务。真实账号须已连接并获授权接收。原生对话和 Events 唤醒需分别观察，不能用合成测试代替；详见 [回环与证据](ROUNDTRIP.zh.md)。

### 可选终态回执

按 [终态回执指南](TERMINAL_RECEIPTS.zh.md) 配置已授权的 Grok routine，可手动发送或显式启用 `ROUNDTABLE_TERMINAL_NOTIFICATIONS=1`。回执仅含任务 ID 和终态。持久账本在发送前预留一次尝试；结果不确定时不自动重发，不保证 exactly-once delivery。

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

首次安装且没有已有秘密管理器凭据时，请改用[托管 setup 与 ui](ONBOARDING_RUNTIME.zh.md#初始化并打开网页)。独立 server 自动生成后会持久保存令牌，但不显示；托管 `ui` 不接管独立启动的进程。

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

需要 HTTP 时，按 [HTTP 配置](HTTP.zh.md) 安全提供 `ROUNDTABLE_HTTP_GRANTS`（群、成员、成员凭据的 JSON 数组），再启动：

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

详细约束见 [安全复核](../SECURITY_REVIEW.md)。

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

