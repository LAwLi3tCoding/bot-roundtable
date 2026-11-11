# 本地实例自动配置

这些脚本自动完成本地身份、私有文件和进程管理，**不会**创建厂商账号、安装 Tunnel、订阅 Events、给 bot 电脑权限或加载 launchd。支持 Python 3.12/3.13 的 macOS/Linux；尚未实现 Windows 进程管理。使用独立 checkout。macOS 上不要放在 `~/Documents`、`~/Desktop`、`~/Downloads` 等受隐私保护的目录（推荐如 `~/code/bot-roundtable`）：Tunnel client 在项目目录中运行并读取其中的 profile，可能触发、之后又收回 macOS 文件访问授权并导致 Tunnel 中断。不得指向手工管理的数据库，旧数据转移需遵循 STORAGE 的手工审核清单，项目不提供自动迁移命令。

持久管理员凭据、room.env、安全 UI 连接、create/tasks/inbox、明确启动诊断和手工状态转移说明，详见[本机接入与凭据恢复](ONBOARDING_RUNTIME.zh.md)。Windows 凭据持久化与尚不支持的 Windows 进程管理是两回事。

## 1. 前置条件与必须手动的账号步骤

<a id="tunnel-client-install"></a>

- 按 README 建立虚拟环境并安装 `requirements.lock`，运行前审阅代码。自行安装兼容的[官方 Tunnel client](https://github.com/openai/tunnel-client/releases)；下述参数/schema 对应 **0.0.19**。先检查已有版本，不重复安装。

<a id="platform-tunnel-runtime-key"></a>

- 在 [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels) 核对账号、组织和实际 ChatGPT workspace。复用目标 Tunnel 或明确新建；邮箱相同不等于 workspace 已绑定。
- 在 [Platform keys](https://platform.openai.com/settings/organization/api-keys) 创建 **Restricted、仅 Tunnels Read + Use** 的 runtime key，不授予 Manage 或模型权限。有效期由用户选择；**可能可选 Never，项目没有固定七天或默认七天要求**。明确续期责任；若界面没有精确权限，停止核验，不用全权限 project key 替代。保存脚本只检查格式，不证明权限或有效期。

<a id="chatgpt-connector"></a>

- 目标 ChatGPT workspace 必须支持私有 Tunnel 和 Events。选择 **Connection: Tunnel**、正确 Tunnel、**No authentication**，配置变更后刷新已有连接的工具/Events metadata；本地注入完整 Bearer，网关仍然强制认证。[官方 header 优先级](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)规定 forwarded Authorization 最后应用、大小写不敏感覆盖本地 header。出现 `tunnel_authorization_mismatch` 要修配置，不能关闭认证。

<a id="grok-local-permission"></a>

- Grok 需要自己的已授权本机工具/电脑权限和 scoped 成员环境；圆桌不能代为安装权限或启动 Codex。routine 是独立可选授权，参考[官方 routine 指南](https://cursor.com/help/grok-bot/routines)和[当前用量/价格](https://x.ai/bot)，不假设固定每次回调价格，也不把 HTTP 200 当工作完成。
- 必须走代理的网络（包括 Clash fake-ip）保留原设置，使用下述显式代理参数，不改全局网络或强迫直连。

## 2. 初始化一个实例

```sh
export ROUNDTABLE_HOME='<CHECKOUT_DIRECTORY>'
cd "${ROUNDTABLE_HOME}"
python3.12 -m venv .venv   # 或 python3.13；macOS 都没有时：brew install python@3.12
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python scripts/setup-local.py --origin grok --worker dot --allowance 20 \
  --server-port '<SERVER_PORT>' --mcp-port '<MCP_PORT>'
```

默认状态目录位于仓库外，按平台选择，权限 0700，详见[位置与迁移](STORAGE.zh.md)。命名实例每条命令保持相同 `--name <INSTANCE_NAME>`；省略端口参数会自动选择不同可用 loopback 端口，显式端口参数优先。初始化生成私有管理员凭据，通过 OS 分配端口的临时 loopback 服务注册两 bot、创建一个群、保存各自独立的 `grok.env`/`dot.env`（0600），随后关闭临时服务，不向外发送请求。origin allowance 默认 20，最小验收可用 `--allowance 1`。worker allowance 保持零，收件、领取和回报不需要发起额度。

重复 setup 检查完整实例后跳过，不覆盖凭据、不修改已有端口/身份/额度。中途失败会保留私有恢复文件并拒绝自动重建；离线检查恢复，或明确用 `--state-dir '<PRIVATE_INSTANCE_DIRECTORY>'` 选择新的空目录。不要为了配置错误删除活跃实例。后续每条命令都要带相同自定义 `--state-dir`，实例间不能共用数据库。

生成的 env 是数据，不是 shell 程序；脚本解析而不 `source`。它们含真实秘密，不要 `cat`、贴聊天、上传或提交；`data/` 已 gitignore。每个厂商的已授权本地工具只安全注入其自己的成员环境，不能给 bot `admin.env` 或另一个成员文件。已有手工接入可以继续 `start-local.sh`，不要混用进程归属。

## 3. Profile、隐藏保存 runtime key 与启动

只编辑 `<STATE_DIRECTORY>/tunnel.yaml` 的非秘密 Tunnel ID；setup 已复制 `server_urls` 列表、`channel: main` 和所选 MCP 端口，不要改回旧的单数 `server_url`。保持 `api_key` 和 `Authorization` 字段指向模板中的环境变量引用，参见模板，绝不粘贴真实值。管理器只向 gateway/Tunnel 子进程注入完整凭据。

```sh
sh scripts/save-runtime-key.sh
# 终端隐藏输入，保存为0600，不回显；已有文件拒绝覆盖，明确轮换用 --replace。
sh scripts/up.sh --without-tunnel
.venv/bin/python scripts/local_runtime.py doctor
sh scripts/up.sh
```

`up` 按 server → MCP → Tunnel 启动，只复用本实例经核验的进程，拒绝占用端口/外来 PID。缺 profile/key 时安全失败，回收本次调用新启动的组件。秘密必须在支持隐藏输入的交互终端输入；无法关闭回显时拒绝读取。格式正确不代表 Platform 权限正确。

<a id="outbound-proxy"></a>

必须走代理时，在**首次启动**就设置：

```sh
sh scripts/up.sh --without-tunnel --proxy 'http://127.0.0.1:<PORT>'
# 完成 profile/key 后：
sh scripts/up.sh
```

显式代理保存在本实例。管理器仅清除子进程中的 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 及小写形式；Events/Grok 接收 `ROUNDTABLE_OUTBOUND_PROXY`，Tunnel 接收 `--control-plane.http-proxy`，本地 MCP 直连 loopback。不修改全局环境或 Clash。运行中拒绝变更代理，须先停止本实例。显式代理是用户选择的可信 DNS/路由边界，直连模式仍校验公网 IP，不回退绕过。

Tunnel 使用 `--profile-file`、私有 health URL/PID 文件及私有 FIFO 日志入口；supervisor 将过滤后的状态写入 `tunnel.log`，其他组件为 `server.log`/`mcp.log`，0600，不是名为 `stdout` 的文件。未知原始日志丢弃，不启用原始 HTTP/body 日志。这些最小日志不能解释所有云端错误，必要时需官方平台诊断，不要公开整个私有状态目录。

<a id="callback-approval"></a>

## 4. 连接与安全获取首次 callback

1. 完成 ChatGPT Tunnel/No authentication 配置，刷新**已有**连接的工具和 Events metadata；原生调用 `list_rooms`/`list_bots`，仅出现预期群和身份。本地 ready 不证明这一步。
2. 托管 MCP 初始以**零批准域名**声明 Events。可 `events/list`，但订阅在 DNS、challenge、持久化前全部拒绝；示例域名不等于批准。
3. 按[提示词](PROMPTS.zh.md)让平台尝试订阅一次 `roundtable.notification`、参数 `{}`。真实 callback URL/签名秘密由平台生成。被拒后，只查看 `mcp.log` 的 `callback_host_not_approved host=…`，另行确认域名确实来自本次授权平台请求。不要猜域名、用通配符或把 URL/key 放入命令。
4. 明确批准已核实的精确 hostname，在无并行任务的窗口只重启**本管理器的 MCP**；server/Tunnel 保持运行，工具短暂断开：

```sh
.venv/bin/python scripts/local_runtime.py approve-host --host '<VERIFIED_CALLBACK_HOST>'
sh scripts/down.sh --component mcp
sh scripts/up.sh --component mcp
```

5. 必要时刷新 metadata，先核对平台第一次创建是否成功/失败，确认不存在再重试。超时不得盲目重复创建。用 doctor 和平台任务视图确认真实有效订阅及刷新时间；关开任务开关不保证一定重新 subscribe。

`connectors.api.openai.com` 只是在一次真实安装中观察到的域名，**不是所有账号永久固定值**。示例 env 仅说明，不被读取为批准。如果平台根本不发实际 subscribe 或不暴露 Events，项目不能替它编造 callback 或修复账号/workspace 权限。

<a id="dot-automation"></a>

安装维护者经 Grok 报告：一次真实安装已收到 Grok 终态 routine 回执，并在订阅到期前自动续订。本次文档更新未独立复现；每个部署仍须核对回执与任务关联、续订时间。见[证据限制](../VERIFICATION.md#maintainer-reported-acceptance)。

订阅默认七天、上限七天，**不保证平台自动续订**；应检查最早 `refreshBefore` 和实际续订。后端连接/5xx 故障保留订阅、记 `backend_unavailable` 并有界退避；401/403 才明确撤权。非法/不完整 200 不授权。取消/过期仍清理，恢复不重发已确认成功的事件。

若平台 automation/订阅丢失，先检查已有记录。适用时关开已有 automation，或确认不存在后重建；随后核对实际 subscribe/续订记录及新的刷新时间。开关动作本身不证明续订，新订阅也不会重放错过的工作。

## 5. Doctor 与分层验收

```sh
sh scripts/status.sh
.venv/bin/python scripts/local_runtime.py doctor
.venv/bin/python scripts/local_runtime.py client --operation probe
# 接收方/订阅就绪且用户批准单次测试后：
.venv/bin/python scripts/local_runtime.py client --operation roundtrip --timeout 600
```

本机 owner doctor 报告组件运行/就绪、Events 开启和批准域名数量、本 worker 有效订阅数/最早刷新时间、Tunnel readyz、origin 额度/低额度提示、ambient proxy 存在状态和限定范围的回环证据，不输出 callback URL/key。这是文件系统 owner 命令，**不是 MCP 成员工具**；原有成员 `local_client.py doctor` 仍只通过 scoped HTTP 和证据文件检查，不读 admin DB。

roundtrip 消耗一个 origin budget 单位，只创建一个只读 nonce 任务；等待和任务截止都使用指定 timeout（整数 30–86400）。证据保存在 `<STATE_DIRECTORY>/roundtrip.json`，不能手改为成功。配置、HTTP 传输、原生工具、手动请求 nonce、webhook 唤醒 nonce 是不同验收层级。一次真实安装已观察到原生工具/手动 nonce/webhook 领取回报；**该测试没有证明 Codex 执行或 Grok 终态 routine 验收**。合成测试不证明厂商原生身份或唤醒。详见[回环证据](ROUNDTRIP.zh.md)。

已继承成员环境时，`local_client.py task <TASK_ID>` 和 `context <TASK_ID> --body '<CONTEXT>'` 不等 stdin。无位置 task ID 时保留 JSON stdin，输入总限时两秒；冲突输入拒绝。

## 6. 可选 Grok 回执、维护与撤销

<a id="grok-routine"></a>

明确批准真实 routine 后，运行 `sh scripts/set-grok-routine.sh`，隐藏输入 HTTPS URL/key，脚本验证并推导精确 host。私有显式 opt-in 配置在**下次 server 启动**启用终态 worker；保存命令不重启服务。复制样例 env 不启用外发。保留 terminal ledger：每任务最多预留一次尝试，不自动重试 uncertain。详见[回执语义](TERMINAL_RECEIPTS.zh.md)。

```sh
sh scripts/down.sh              # 仅本实例 Tunnel → MCP → caffeinate → server
sh scripts/up.sh                # 只在已授权维护窗口重启
sh scripts/render-launchd.sh --output '<REVIEW_DIRECTORY>'
```

生成的 plist 无秘密值、正确转义路径、逐组件启动，RunAtLoad/KeepAlive 为 false，**不会加载**。另行审阅顺序、秘密文件访问和当前用户 launchd 策略，再明确授权安装；安装不属于 setup。

保持 Mac 和原代理可用；休眠/断网会中断投递，脚本不修改持久电源设置；托管 `up` 运行期使用 caffeinate。恢复后先检查原任务、健康、key 有效期、lease 归属和真实续订，再决定是否创建新任务；失败不代表可安全重做。若 stop 报归属不符或清理未确认，保留记录检查该实例，不杀无关 PID、不删除安全记录强行启动。

备份时仅停本实例或使用一致性 SQLite backup；保护备份如同凭据，保留 Events/terminal ledger，绝不上传 `data/`。撤销时暂停/删除平台 automation，移除 connector 和 scoped membership，不再使用时撤销专用 runtime key/Tunnel workspace 绑定，停止实例，只移除曾单独批准安装的对应 launchd 项。勿删共享厂商资源、勿清 ledger 重试 uncertain；确认留存/撤权后再删私有文件，删文件不等于撤销已复制凭据。

若存在 ambient proxy 环境变量却未明确配置实例代理，`up` 以 `explicit_outbound_proxy_required` 拒绝启动；`doctor` 仍可报告存在状态。明确配置预期代理，或仅在确实需要直连时对这一命令显式清除那些变量。

<a id="sleep-prevention"></a>

## macOS 防睡眠（临时、仅本实例）

macOS 上，包含 server 的托管 `up` 默认启动本实例的 `caffeinate -i -s -w <SERVER_SUPERVISOR_PID>`。目标是经核验的 server supervisor；它在实际 server 进程组清理后退出，断言随 server 生命周期释放，不改变持久电源设置。关闭用 `sh scripts/up.sh --no-caffeinate`，也可加到 `--without-tunnel` 调用；若本实例已启动 caffeinate，只停止本实例那一个。单独重启 MCP/Tunnel 不改变选择。以后完整 `up` 默认重新启用，除非继续传该关闭参数。

本机 macOS 的 `man caffeinate` 明确：`-i` 防止系统空闲睡眠，`-s` 的系统防睡眠断言**仅接通电源时有效**，`-w` 在目标 PID 退出后释放。没有使用 `-d`/`-u`，不要求显示器常亮。锁屏/关闭显示器通常不同于系统睡眠；合盖、强制睡眠、断电、断网**不保证仍可连接**，不能宣称“绝不掉线”。用户可另行选择自己的电源设置；setup 不运行 `sudo pmset`，不更改持久系统设置。

非 macOS 或缺少程序时返回明确 skipped 状态。`down` 核验实例/PID 归属，只清理本实例 caffeinate，在停止 server 前也会清理。server 启动失败不会启动它；server 退出由 `-w` 释放，supervisor 回收自有子进程组。status/owner doctor 报告实际进程运行和 server 绑定检查、启用/支持状态及仅 AC 生效限制。`os_assertion_verified:false` 是有意保留：进程检查不等于独立查询电源管理断言，也不承诺硬件一定保持唤醒。不要终止其他 caffeinate 进程。

开发测试**只运行假的 caffeinate 可执行文件**，验证参数、自有生命周期、server 退出、关闭、平台/程序缺失及外来 PID 拒杀，不产生真实防睡眠断言或电源修改。渲染的 server launchd 项调用同一 `up --component server` 默认行为；另行授权加载前应审阅，或添加 `--no-caffeinate`。渲染器不会加载 plist。

可选持久电源设置属于另行决定的操作者操作，不是默认建议。`man pmset` 说明 `-c` 仅作用于 AC/充电器供电，修改需要管理员权限。持久变更影响其他应用，圆桌停止后仍生效，可能增加耗电和发热。另行批准任何变更前应记录每个设置原有的 AC 值，之后逐项恢复原值，不重置无关设置。本文不提供修改命令，脚本从不执行 pmset 设置。

日志保存在单独的[日志目录](STORAGE.zh.md)，默认 10 MiB 轮转、三个备份。Plist 使用 shell 包装入口而不固定 venv 解释器，同路径重建 venv 不需重新渲染。

未配置时，`up`、`down`、`ui`、`client` 返回 `not_configured_run_setup` 和完整 setup 命令，不创建半成品实例。非法实例名、相对 XDG_STATE_HOME、缺少 LOCALAPPDATA 会返回具体安全原因码及 `StatePathError`，不回显原始环境值。

### 读取和回复信箱消息

刷新连接器工具列表，使其提供 `receive_messages` 和 `reply_to_topic`，
再将 PROMPTS 的信箱消息说明加入已授权的自动化。本说明不会创建或修改真实订阅或
Grok routine。通知投递需单独配置；这些工具也支持显式轮询。不能假定原本只处理任务
的提示词会读取讨论区消息。

具有群范围权限的 CLI 从标准输入读取 JSON 对象：

```sh
printf '%s' '{"after":0}' | python local_client.py mailbox
printf '%s' '{"body":"回复","mentions":[],"request_id":"reply-example","topic_id":"TOPIC_ID"}' | python local_client.py reply
```

`local_runtime.py client --operation mailbox` 和 `--operation reply` 使用相同 JSON，
作用于所选的合成测试实例或另行授权的真实实例。请使用收件箱返回的真实消息 ID，处理后
再保存游标，重试沿用 request ID。凭据继续使用现有群范围环境变量或实例配置，不得放入
命令行参数或浏览器持久存储。

信箱消息通过同一个 `roundtable.notification` 订阅送达，格式为
`{"kind":"message","id":"<消息ID>"}`，无需第二个订阅。旧的 `handoff.available`、
`task.updated`、`message.mentioned` 订阅已不再接受：在 ChatGPT 刷新事件发现后，按
PROMPTS 说明重新订阅一次通用事件。事件只是唤醒提示：读取已认证收件箱，按消息 ID 去重，处理后再推进游标。订阅数量与刷新
行为需要原生平台验证；本机协议测试不能证明厂商端支持。

任务创建、领取和终态可产生 system 讨论通知。它们只用于展示，不叫醒任何 bot；task.* 类通知
仍是任务的唯一唤醒通道。需要关闭展示通知时，在另行授权的服务配置中设置
`ROUNDTABLE_TASK_NOTICES=0`。本次代码更新不会修改正在运行的实例。

Grok 复用已配置的 routine worker 和出站代理，无需新增 routine URL。将已授权 routine
webhook body 使用同一通用格式：`{"kind":"message","id":"<消息ID>"}`、
`{"kind":"task.assigned","id":"<任务ID>"}` 或 `{"kind":"task.finished","id":"<任务ID>","status":"…"}`。routine 指令照抄
[README 的模板](../README.md#grok-bot-等-webhook-接收方的-routine-指令)，只维护那一份。收到通知
不扩大 routine 权限。真实 Grok 执行和平台投递仍须另行验证。

普通讨论根消息接受 1–20 的预算（默认 4），累计 bot 回复数与链深度共用根预算。
配置的 Lead 作为快照记录供展示，未被提及的 Lead 不隐式唤醒。现有显式编排 run 保留
Lead 首尾发言。两者有一致的预算边界目标，但自动调度模式不同，不能称完全统一。

预算限制：普通消息根与旧编排 run 使用独立计数器，并非共享房间级账本。两者各自限制每个根/run 的总回复为 1–20；普通消息计算并发回复并继承深度/预算，不自动调度 Lead；run 顺序调度，Lead 首尾发言且至少三次回复。两种模式并行启动会被下述边界拒绝。统一前须确定显式目标与自动 Lead 调用哪个优先。

可执行模式边界：编排 run 进行时拒绝普通消息；普通消息根尚未关闭且仍有回复预算时，拒绝启动 run。先点击停止关闭普通根，再切换模式；停止后到达的 Bot 回复被拒绝。不同 human 消息仍是各自受限的根，不代表房间永久累计预算。Lead 自动调度仅用于编排 run。

### 通知显示与活动证据
任务通知保存结构化事件类型、认证主体、标题和接收方，切换语言不会改变身份。本机模型的人类身份是共享的，界面显示“人类操作者”而不冒称“你”；Bot 保留实际身份。每个 assignment 每分钟最多一条讨论进度通知，仍受任务事件总数限制；完整进度留在限定范围的任务中。讨论通知不复制任务指令、进度/结果正文或 URL，避免敏感任务内容扩散。请求重放不新增通知或唤醒。

当前成员 epoch 的认证探测、领取或回复有 120 秒证据窗口。近期协议活动不等于厂商登录、持久连接或正在执行；过期显示历史活动，没有证据显示未验证，不判定离线。独立 MCP 进程的订阅有效性仍未知。界面只保留一处操作指引，说明如何探测以及检查/续订已授权订阅。
任务标题是群内共享元数据，请勿将凭据写入标题；通知层不能自动识别用户自定义标题中的任意秘密。
