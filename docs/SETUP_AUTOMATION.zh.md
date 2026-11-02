# 本地实例自动配置

这些脚本自动完成本地身份、私有文件和进程管理，**不会**创建厂商账号、安装 Tunnel、订阅 Events、给 bot 电脑权限或加载 launchd。支持 Python 3.12/3.13 的 macOS/Linux；尚未实现 Windows 进程管理。使用独立 checkout，不得指向手工管理的数据库或 `data/local-runtime`。

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
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python scripts/setup-local.py --origin grok --worker dot --allowance 20 \
  --server-port '<SERVER_PORT>' --mcp-port '<MCP_PORT>'
```

默认状态目录 `data/local` 为 0700。初始化生成私有管理员凭据，通过 OS 分配端口的临时 loopback 服务注册两 bot、创建一个群、保存各自独立的 `grok.env`/`dot.env`（0600），随后关闭临时服务，不向外发送请求。origin allowance 默认 20，最小验收可用 `--allowance 1`。worker allowance 保持零，收件、领取和回报不需要发起额度。

重复 setup 检查完整实例后跳过，不覆盖凭据、不修改已有端口/身份/额度。中途失败会保留私有恢复文件并拒绝自动重建；离线检查恢复，或明确用 `--state-dir '<PRIVATE_INSTANCE_DIRECTORY>'` 选择新的空目录。不要为了配置错误删除活跃实例。后续每条命令都要带相同自定义 `--state-dir`，实例间不能共用数据库。

生成的 env 是数据，不是 shell 程序；脚本解析而不 `source`。它们含真实秘密，不要 `cat`、贴聊天、上传或提交；`data/` 已 gitignore。每个厂商的已授权本地工具只安全注入其自己的成员环境，不能给 bot `admin.env` 或另一个成员文件。已有手工接入可以继续 `start-local.sh`，不要混用进程归属。

## 3. Profile、隐藏保存 runtime key 与启动

只编辑 `data/local/tunnel.yaml` 的非秘密 Tunnel ID；setup 已复制 `server_urls` 列表、`channel: main` 和所选 MCP 端口，不要改回旧的单数 `server_url`。保持 `api_key` 和 `Authorization` 字段指向模板中的环境变量引用，参见模板，绝不粘贴真实值。管理器只向 gateway/Tunnel 子进程注入完整凭据。

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
3. 按[提示词](PROMPTS.zh.md)让平台尝试订阅一次 `handoff.available`、参数 `{}`。真实 callback URL/签名秘密由平台生成。被拒后，只查看 `mcp.log` 的 `callback_host_not_approved host=…`，另行确认域名确实来自本次授权平台请求。不要猜域名、用通配符或把 URL/key 放入命令。
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

订阅默认一小时、上限一小时，**不保证平台自动续订**；应检查最早 `refreshBefore` 和实际续订。后端连接/5xx 故障保留订阅、记 `backend_unavailable` 并有界退避；401/403 才明确撤权。非法/不完整 200 不授权。取消/过期仍清理，恢复不重发已确认成功的事件。

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

roundtrip 消耗一个 origin budget 单位，只创建一个只读 nonce 任务；等待和任务截止都使用指定 timeout（整数 30–86400）。证据保存在 `data/local/roundtrip.json`，不能手改为成功。配置、HTTP 传输、原生工具、手动请求 nonce、webhook 唤醒 nonce 是不同验收层级。一次真实安装已观察到原生工具/手动 nonce/webhook 领取回报；**该测试没有证明 Codex 执行或 Grok 终态 routine 验收**。合成测试不证明厂商原生身份或唤醒。详见[回环证据](ROUNDTRIP.zh.md)。

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
