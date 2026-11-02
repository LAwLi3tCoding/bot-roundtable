# dot 私有交接配置

新安装优先使用[实例自动配置](SETUP_AUTOMATION.zh.md)。以下手工命令保留为另一种方式，不能让两套管理器接管同一实例。


这里只提供待操作人审核的模板，不安装客户端、不加载 launchd、不创建密钥、不订阅 Events、不发送 routine。

1. 选择独立 checkout，把 `ROUNDTABLE_HOME` 设置为其绝对路径。用 Python 3.12/3.13 创建 `.venv` 并安装 `requirements.lock`。按 README 通过已批准的秘密管理器/环境提供管理员凭据，创建专用群；Grok 和 dot 使用独立成员凭据，发起额度先保持 0。秘密不得放入命令正文、源码或聊天。
2. 在管理员环境中运行 `sh scripts/start-local.sh server`，仅绑定 loopback。已有实例占用端口或数据库时不得重复启动。
3. 通过安全环境引用设置 dot 的 `ROUNDTABLE_URL`、`ROUNDTABLE_ROOM`、`ROUNDTABLE_AGENT`、`ROUNDTABLE_TOKEN`。执行 `.venv/bin/python scripts/check.py doctor` 和 `probe`。包装器不打开秘密文件、关闭 stdin、总时限 15 秒；成功仅证明传输。
4. 按 `docs/HTTP.zh.md` 设置只包含目标 dot 成员的 `ROUNDTABLE_HTTP_GRANTS`。安全设置 `ROUNDTABLE_TUNNEL_AUTH_HEADER` 为完整的 `Bearer <dot scoped token>`，网关用它限制固定身份。执行 `sh scripts/start-local.sh mcp`，默认仅本机 8766。
5. 按下文“实测的 Platform、Tunnel 与 ChatGPT 配置”完成官方客户端、受限 runtime key、工作区绑定和 profile-file 配置；这些仍是操作者的一次性步骤。
6. 此私有固定身份路线在 ChatGPT connector 选择 **No authentication**，由 tunnel 注入本地 Bearer；网关认证仍然开启。官方[配置参考](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)明确 forwarded connector headers 最后应用，大小写不敏感地覆盖 `mcp.extra_headers`。发生 Authorization 冲突或缺失时，本网关返回 `tunnel_authorization_mismatch`，不记录值。禁止关闭认证凑通。值相同无法区分注入与转发，必须从真实 connector 调用 `list_rooms`/`list_bots` 核对唯一群和身份；doctor 不代表端到端验收。
7. 用户批准后才给入口小额额度：在管理员环境执行 `.venv/bin/python scripts/admin.py allowance <room-id> <origin-agent> 1`。不得把管理员 token 给 Bot。订阅、原生 Codex 执行、routine 配置分别受用户授权范围限制。

`deploy/launchd/` 模板默认不运行。`${ROUNDTABLE_HOME}` 是渲染占位符，launchd 不会自动展开；本地替换为绝对路径、安全注入环境（含官方 tunnel 二进制 PATH）、审核权限和生命周期，获得批准后才加载。不得把秘密粘贴到 tracked plist。前台进程用 Ctrl-C 停止，管理的后台进程先核对归属再发信号。模板不配置自动重启。

## 从零开始：前置条件与本机身份

需要 Git、Python 3.12/3.13、一个可持续运行的本机环境及浏览器。本文的 shell、权限和手动进程命令面向 macOS/Linux；Windows 需等价的当前用户 ACL 与进程管理，未在本次实测中验证。仅本机 demo 不需要厂商账号。私有云端接入另需有创建 Tunnel 权限的 Platform 组织、可绑定的 ChatGPT workspace、支持自定义 MCP/Tunnel 和 Events 的产品入口；先确认这些能力实际可见，不假定所有账号或套餐都支持。

```sh
git clone '<REPOSITORY_URL>' '<CHECKOUT_DIRECTORY>'
export ROUNDTABLE_HOME='<CHECKOUT_DIRECTORY>'
cd "${ROUNDTABLE_HOME}"
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
umask 077
mkdir -p data
chmod 700 data
export ROUNDTABLE_PORT='<SERVER_PORT>'
export ROUNDTABLE_URL='http://127.0.0.1:<SERVER_PORT>'
export ROUNDTABLE_DB="${ROUNDTABLE_HOME}/data/roundtable.db"
```

把 checkout 占位符换成绝对路径，两个 server 端口保持一致；所有后续终端都需设置相同的非秘密路径/端口。已有 checkout 或环境无需重复 clone/创建。使用已有代理联网安装依赖时保留必要代理，不修改全局网络。Tunnel 客户端从[官方发行页](https://github.com/openai/tunnel-client/releases)按系统/架构取得，按官方说明核验来源后安装到 PATH；先运行 `tunnel-client --version`，已有兼容版本不必重装。以下 Tunnel 步骤以 0.0.19 为实测基准。

管理员秘密由可信密码管理器生成并保管（至少 32 字符的随机值）。未有进程级秘密注入工具时，可在本机交互终端使用下列隐藏输入示例启动 server；秘密不会进入命令正文或 shell 历史，启动器只将其交给子进程。无可用隐藏输入时直接失败，不回退到明文输入：

```sh
cd "${ROUNDTABLE_HOME}"
.venv/bin/python -c 'import getpass, os, warnings; warnings.simplefilter("error", getpass.GetPassWarning); os.environ["ROUNDTABLE_ADMIN_TOKEN"] = getpass.getpass("Administrator secret (hidden): "); os.execvp("sh", ["sh", "scripts/start-local.sh", "server"])'
```

server 在前台运行，另开浏览器访问本机 `ROUNDTABLE_URL`。点“连接”并输入管理员秘密，注册两个非 demo Bot 身份，在新建专用群时选择它们（或将已注册身份加入该群）。将页面给出的 room ID、各 agent ID 与各自 **agent token** 保存到密码管理器；owner/room token 和管理员秘密不能发给 Bot。首次展示秘密时不要截图/共享页面。每个成员/群绑定使用独立 token；如遗失，按移除再加入的流程生成新凭据并更新相关网关，不能从摘要恢复旧 token。

接下来在另一个终端设置 dot 的 `export ROUNDTABLE_ROOM='<ROOM_ID>'`、`export ROUNDTABLE_AGENT='<DOT_AGENT_ID>'` 和 `export ROUNDTABLE_MCP_PORT='<MCP_PORT>'`。两个身份的 token 不互换。默认不需要给接收者发起额度；只有发起 roundtrip 的入口成员需要 1 单位。

本机 doctor 的隐藏输入示例（把最后的 `doctor` 换成 `probe` 可做连接观测；probe 会写观测，不派任务）：

```sh
.venv/bin/python -c 'import getpass, os, sys, warnings; warnings.simplefilter("error", getpass.GetPassWarning); os.environ["ROUNDTABLE_TOKEN"] = getpass.getpass("Member token (hidden): "); os.execv(sys.executable, [sys.executable, "scripts/check.py", "doctor"])'
```

只授予此 dot 身份的网关启动示例；保留前台终端，不另起同端口实例。按需先设置本指南的显式出站代理变量：

```sh
.venv/bin/python -c 'import getpass, json, os, warnings; warnings.simplefilter("error", getpass.GetPassWarning); token = getpass.getpass("Dot member token (hidden): "); os.environ["ROUNDTABLE_HTTP_GRANTS"] = json.dumps([{"room": os.environ["ROUNDTABLE_ROOM"], "agent": os.environ["ROUNDTABLE_AGENT"], "token": token}]); os.environ["ROUNDTABLE_TUNNEL_AUTH_HEADER"] = "Bearer " + token; os.execvp("sh", ["sh", "scripts/start-local.sh", "mcp"])'
```

这些是可审阅的交互命令示例，不是仓库自动保存/配置工具；终端之间不会自动共享后来设置的环境。Tunnel doctor/run 也需独立注入 `CONTROL_PLANE_API_KEY` 和同一成员的完整 Bearer。可将下方命令作为参数传给隐藏输入启动器，例如：

```sh
.venv/bin/python -c 'import getpass, os, sys, warnings; warnings.simplefilter("error", getpass.GetPassWarning); os.environ["CONTROL_PLANE_API_KEY"] = getpass.getpass("Tunnel runtime key (hidden): "); os.environ["ROUNDTABLE_TUNNEL_AUTH_HEADER"] = "Bearer " + getpass.getpass("Dot member token (hidden): "); os.execvp(sys.argv[1], sys.argv[1:])' tunnel-client doctor --profile-file "${ROUNDTABLE_HOME}/data/tunnel/roundtable.yaml" --health.listen-addr 127.0.0.1:0 --explain
```

先完成下节的 profile/key 配置再运行此示例。运行 Tunnel 时，用下节完整 `tunnel-client run …` 命令替换示例末尾的 `tunnel-client doctor …`；需要代理时同样追加控制面代理参数。权限/额度命令亦可用同样的 `getpass`+子进程方法只注入管理员变量，避免复制秘密到 `export` 命令。持续运行环境应改用自己已批准的秘密管理方式，并保护进程环境访问权限。

## 实测的 Platform、Tunnel 与 ChatGPT 配置

以下命令按官方 `tunnel-client 0.0.19` 的帮助和配置格式核对；产品界面可能变化，应核对同名操作和最终状态。安装软件与创建账号权限由操作者完成，本文不提供自动开户或密钥生成脚本。只做本机工具调用时可停在前述第 4 步，不必配置 Tunnel/Events。

1. **创建 Tunnel。** 在 [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels) 核对账号及组织，先检查是否已有目标 Tunnel，避免重复创建。创建时填写名称/描述，授权预期 organization 和实际使用的 ChatGPT workspace；保存 Tunnel ID。只给目标工作区访问权，不把“同一邮箱”当作工作区绑定已经完成。
2. **创建最小权限 runtime key。** 在 [API keys](https://platform.openai.com/settings/organization/api-keys) 选择预期项目、命名 key、选择 **Restricted**，只启用 **Tunnels Read、Use**，其他权限均为 None，不授予 Manage 或模型调用权限。明确选择有效期并记录续期责任。若界面不能提供这些精确权限，停止并核实支持方式，不用 All/project 全权限 key 替代。
3. **安全保存。** 用已批准的秘密管理器或本机隐藏输入保存 key，仅向 Tunnel 进程提供 `CONTROL_PLANE_API_KEY`。本机文件和目录分别限制为 `600`、`700`，置于 Git 忽略的 `data/` 下；用 `git check-ignore <path>` 核对，勿用 `cat` 验证秘密。不要把 key 写进命令正文、聊天、截图、日志、tracked YAML/plist，或设置成 Codex 的 `OPENAI_API_KEY`。成员 token 与 Platform key 不是同一凭据：`ROUNDTABLE_TUNNEL_AUTH_HEADER` 必须安全注入完整的 scoped `Bearer …`，与网关固定 dot 成员一致。仓库没有自动读取或保存这些秘密的安装器。
4. **准备 profile。** 先安全提供上述环境，再创建私有目录并复制模板：

```sh
umask 077
mkdir -p "${ROUNDTABLE_HOME}/data/tunnel"
chmod 700 "${ROUNDTABLE_HOME}/data/tunnel"
cp -n "${ROUNDTABLE_HOME}/examples/tunnel-client.yaml" "${ROUNDTABLE_HOME}/data/tunnel/roundtable.yaml"
chmod 600 "${ROUNDTABLE_HOME}/data/tunnel/roundtable.yaml"
```

只在首次配置、目标文件尚不存在时复制，勿覆盖已有配置。编辑本地副本的 `<TUNNEL_ID>` 和实际 MCP 端口；YAML 使用 `mcp.server_urls` 列表（`channel: main`、`url`），不是旧的 `server_url`。`env:VARIABLE` 是客户端支持的秘密引用；不要假设 YAML 会展开 shell 的 `${...}`。

5. **检查并手动运行。** 以下直接使用官方 `--profile-file`，不依赖命名 profile 的查找目录：

```sh
tunnel-client doctor --profile-file "${ROUNDTABLE_HOME}/data/tunnel/roundtable.yaml" --health.listen-addr 127.0.0.1:0 --explain
tunnel-client run --profile-file "${ROUNDTABLE_HOME}/data/tunnel/roundtable.yaml" --health.listen-addr 127.0.0.1:0 --health.url-file "${ROUNDTABLE_HOME}/data/tunnel/health.url" --pid.file "${ROUNDTABLE_HOME}/data/tunnel/tunnel.pid" --log.file "${ROUNDTABLE_HOME}/data/tunnel/runtime.log" --log.http-raw-unsafe=false
```

需要既有 HTTP CONNECT 代理时，给 **doctor 和 run 两条命令**都追加 `--control-plane.http-proxy env:ROUNDTABLE_OUTBOUND_PROXY`，该环境变量值为 `http://127.0.0.1:<PORT>`。这是 Tunnel 客户端自己的选项，项目的代理变量不会自动配置它。不要设置全局 `--http-proxy` 去代理本机 MCP；在此启动进程中移除继承的 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 及小写形式，让控制面走显式代理、本机 MCP 保持直连，不改变系统或 Clash 配置。

`--profile <name>` 仍是官方支持的另一条路线，但文件须位于客户端 profile 目录或通过 `--profile-dir` 指定；`scripts/start-local.sh tunnel` 支持 `ROUNDTABLE_TUNNEL_PROFILE_FILE` 文件路径，或 `ROUNDTABLE_TUNNEL_PROFILE` 命名路线。不要将文件路径误当 profile 名。实测 0.0.19 中显式 `--log.file stdout` 创建了名为 `stdout` 的文件，因此这里使用私有绝对日志路径，不依赖这个字符串代表标准输出。原始 HTTP 日志保持关闭；不要公开整个健康详情或日志，其中可能含本机路径和请求信息。

doctor 检查分层解读：profile 解析、key 引用和 loopback 可达不证明云端成功。固定 Bearer/No authentication 路线在 0.0.19 的 doctor 可能单独报 `oauth_metadata` 缺失；不能关认证或伪造 metadata。确认带认证的本机 MCP initialize 成功，再核实运行时健康的 `ready`、control-plane polling/last_success、代理路由及 OAuth `not_advertised`。只有这些证据一致时，才把此项归为未使用的 OAuth 发现检查；其他失败必须修复。运行时 ready 仍不等于原生工具调用成功。

6. **创建并连接 ChatGPT 插件。** 在预期账号/工作区的插件页使用“添加自定义 MCP 服务器”（入口名称可能变化），名称自定，Connection 选择 **Tunnel**，输入/选择同一 Tunnel，Authentication 选择 **No authentication**，然后完成创建和连接。后端认证保持开启。只连接已授权测试群的 dot 身份，不安装重复插件。
7. **刷新并验证。** 在既有插件管理页使用“刷新工具”，尤其是网关后来启用了 Events 时。真实 Dot 会话重新发现工具，调用 `list_rooms`、`list_bots` 核对唯一群和预期成员。另核 `initialize.capabilities.events`、`events/list` 及产品事件来源/schema；有工具不代表平台已发现事件。平台可能需要刷新当前会话，不能把另一个线程可见当成本线程可见。

## 首次 Events 发现限制与订阅确认

**安全首次发现：** 当前可启用 Events 并保持空 callback 白名单，声明事件但在 DNS/challenge/持久化前拒绝所有订阅。从平台真实请求和安全拒绝日志取得 hostname，另行核实来源，明确精确批准后仅重启受管理的网关。不猜域名、不关闭校验。详见[自动配置首次接入](SETUP_AUTOMATION.zh.md)。

已有可信精确白名单且 Events 正常启动时，按以下顺序操作：

1. 刷新插件发现，确认 `handoff.available` 的参数为 `{}`，由产品生成真实 callback URL 和签名秘密，不手工伪造。
2. 明确要求订阅本成员任务。只使用事件触发，不添加独立轮询计划。若实际请求被拒，读取安全日志的 `callback_host_not_approved host=…`，只核实 hostname 与预期平台来源；日志或域名外观本身不是信任证明。确认为本次授权平台后，精确批准新 host，在无并行任务时仅重启受影响的 MCP 网关，保留原私有 Events DB，然后重试。不要把一次观察的域名当所有账号永久固定值。
3. 创建报错/超时时，先查平台是否已有 automation/subscription，再核网关订阅状态；结果不确定不得重复创建。区分平台创建前 connector 校验失败、callback 白名单拒绝、challenge 失败。缺少访问日志时，不能断言“请求从未到达”。
4. 确认订阅确实成功且未过期后，才发起一条只读 roundtrip。收到事件不等于执行成功，必须关联领取和回报结果；详见[回环验收](ROUNDTRIP.zh.md)。

## 常驻运行、到期与恢复

安装维护者经 Grok 报告：一次真实安装已观察到终态 routine 回执和到期前自动续订。本次文档更新未独立复现，每个部署仍须核验任务/回执关联、订阅记录及刷新时间。见[证据限制](../VERIFICATION.md#maintainer-reported-acceptance)。

本机 server、MCP 网关、Tunnel 进程和所需代理必须持续可用；电脑休眠/断网、手动进程退出都会中断链路。保存各自非秘密 PID/健康地址，停止前核对归属；只改网关配置时不要停 server。手动启动不等于已配置开机自启。下述 launchd 模板需另行渲染、秘密注入和明确加载，本文命令不会加载它。

Platform key 有自己的到期时间；到期前按相同最小权限安全更新，仅重启需要新环境的 Tunnel。Events 默认及最长订阅期限均为一小时；操作者须确认所用产品能续订并观察有效期，仓库没有替所有客户端自动续订的控制器。新订阅从当前事件边界开始，不提供历史重放；短暂断线不应通过删除数据库、重建任务或重置额度掩盖。恢复后重查原任务、订阅有效期和健康状态；保留并保护 Events DB，因为它含 callback 签名秘密。

## 租约与回调运行参数

`claim_assignment(..., lease_seconds=60)` 接受 30–1800 的整数；租约和进度续期均不超过任务截止时间，进度按所选租约时长续期。任务 `timeout_seconds` 范围为 30–86400。过期后可在次数与预算范围内重新领取，旧租约不能继续报告。外部 Codex 操作不会自动撤销或重放。

Events 仍须明确配置并经授权订阅。`ROUNDTABLE_EVENT_TIMEOUT` 控制含 DNS 与传输在内的回调总期限，默认 20 秒，范围 0.01–120。未设置显式代理时，普通代理环境变量触发失败关闭；明确使用可信 HTTP CONNECT 代理时设置 `ROUNDTABLE_OUTBOUND_PROXY`（兼容 `ROUNDTABLE_EVENT_PROXY`）为 HTTP origin，不支持代理凭据。直连时回调 DNS 全部结果必须为公网地址并固定所选 IP；显式代理时 CONNECT 使用规范化域名，由可信代理解析，TLS 与 Host 保留该域名。不跟随重定向或回退直连。不可中断 DNS 在结束前继续占用有界工作槽位。主机拒绝日志仅含 `callback_host_not_approved` 和清理过的 hostname。

另行批准订阅后，`handoff.available` 流程为 receive_assignments → claim_assignment → dot 核对任务及用户权限，通过自身已连接电脑工具创建 Codex 任务 → report progress → completed/failed。事件只是唤醒提示，不是新增授权；任务文本不能越过已批准的范围。

配置获得批准后，可显式启用 Events 入口：

```sh
sh scripts/start-local.sh mcp --events-db "${ROUNDTABLE_HOME}/data/events.db" --event-host approved.hostname
```

此简写仅适用于秘密管理器已向**当前启动进程**注入 grants/Bearer 的情形；前面的隐藏输入启动器不会把秘密留在父 shell。若采用交互隐藏输入，先优雅停止自己管理的旧 MCP（不要停 server），再重用下面的完整启动器，并将 `<EXACT_APPROVED_CALLBACK_HOST>` 替换为已核实批准的实际域名：

```sh
.venv/bin/python -c 'import getpass, json, os, warnings; warnings.simplefilter("error", getpass.GetPassWarning); token = getpass.getpass("Dot member token (hidden): "); os.environ["ROUNDTABLE_HTTP_GRANTS"] = json.dumps([{"room": os.environ["ROUNDTABLE_ROOM"], "agent": os.environ["ROUNDTABLE_AGENT"], "token": token}]); os.environ["ROUNDTABLE_TUNNEL_AUTH_HEADER"] = "Bearer " + token; os.execvp("sh", ["sh", "scripts/start-local.sh", "mcp", "--events-db", os.path.join(os.environ["ROUNDTABLE_HOME"], "data/events.db"), "--event-host", "<EXACT_APPROVED_CALLBACK_HOST>"])'
```


将 `approved.hostname` 替换为明确批准的回调域名；多个域名重复传入 `--event-host`。脚本原样转发参数。默认 `mcp` 命令和 launchd 模板仍关闭 Events。使用 launchd 时，在 `mcp` 后把同样的参数逐项添加为 `ProgramArguments` 字符串，数据库路径需渲染为绝对路径，加载前审核。这里只启用入口；实际订阅 `handoff.available` 仍须在实现验收后取得用户另行确认。

## 本机必须走代理（如 Clash fake-ip）

在 MCP Events gateway 和 server/routine 进程环境中都设置 `ROUNDTABLE_OUTBOUND_PROXY` 为 `http://127.0.0.1:<PORT>`，将 `<PORT>` 替换为已有本机 HTTP CONNECT 代理端口。项目不读取或修改 Clash、系统 DNS 或全局网络配置。兼容的 `ROUNDTABLE_EVENT_PROXY` 同样适用于两条通道；两者同时设置时，非空的统一变量优先，不回退直连。

显式代理是用户选择的可信 DNS/路由边界：CONNECT 传规范化目标域名，不传本机解析出的 fake IP，因此此模式不会因本机 fake-IP 结果而拒绝。本机无法证明代理最终访问的 IP 为公网。精确域名白名单、HTTPS、原主机证书校验及拒绝 IP 字面量/本地域名仍保留。直连模式仍执行本机 DNS、公网 IP 校验和固定。

只有普通 `HTTPS_PROXY`/`HTTP_PROXY`/`ALL_PROXY` 而未设置显式配置时，返回 `explicit_outbound_proxy_required`。`doctor` 返回安全的 `outbound_local`、`outbound_backend`、`terminal_worker` 字段；gateway 环境可能不同，须单独设置。这些只是配置观测，不代表真实厂商可达。配置错误不会消耗终态回执预留，修复后可继续；已经预留且不确定的尝试绝不自动重放。

## 环境变量与启动模板

`start-local.sh` 不读取配置或秘密文件，原样继承调用进程的环境，并转发附加参数。下表区分脚本参数与 Python 进程配置；仅设置 `ROUNDTABLE_PORT` 不会同步改变客户端的 `ROUNDTABLE_URL`。

| 变量 | 使用方与配置 |
|---|---|
| `ROUNDTABLE_HOME` | 启动脚本必需；checkout 的绝对路径 |
| `ROUNDTABLE_PORT` / `ROUNDTABLE_DB` | 脚本传给 server 的端口与数据库；默认 8765 / `data/roundtable.db` |
| `ROUNDTABLE_ADMIN_TOKEN` | server 和 allowance 命令；通过安全环境注入至少 32 字符的随机秘密 |
| `ROUNDTABLE_URL` | bridge、HTTP 网关、本机客户端和 allowance；默认 `http://127.0.0.1:8765` |
| `ROUNDTABLE_ROOM` / `ROUNDTABLE_AGENT` / `ROUNDTABLE_TOKEN` | stdio bridge 与本机客户端的群、成员和独立成员凭据 |
| `ROUNDTABLE_MCP_PORT` / `ROUNDTABLE_HTTP_GRANTS` | 脚本传给 MCP 网关的端口（默认 8766）；网关必需的成员授权 JSON，格式见 [HTTP](HTTP.zh.md) |
| `ROUNDTABLE_OUTBOUND_PROXY` | server/routine 与 Events 网关分别配置；`http://127.0.0.1:<PORT>`，无凭据的可信 HTTP CONNECT 代理 |
| `ROUNDTABLE_EVENT_PROXY` | 出站代理兼容变量；非空 `ROUNDTABLE_OUTBOUND_PROXY` 优先 |
| `ROUNDTABLE_EVENT_TIMEOUT` | Events 回调总期限；默认 20 秒，范围 0.01–120 |
| `ROUNDTABLE_TUNNEL_AUTH_HEADER` | MCP 网关固定成员身份校验；安全注入完整 Bearer header |
| `ROUNDTABLE_TUNNEL_PROFILE_FILE` / `ROUNDTABLE_TUNNEL_PROFILE` | `start-local.sh tunnel` 使用已审核文件路径，或本地 profile 名称 |
| `ROUNDTABLE_EVIDENCE` | 本机客户端默认回环证据路径；默认 `data/roundtrip.json`，可由 `--evidence` 覆盖 |
| `ROUNDTABLE_TERMINAL_NOTIFICATIONS` | 仅值 `1` 启用 server 终态工作器，默认关闭 |
| `ROUNDTABLE_TERMINAL_ROOM` / `ROUNDTABLE_TERMINAL_ORIGIN` | 终态工作器限定的群与当前入口成员 |
| `ROUNDTABLE_TERMINAL_LEDGER` | 手动及自动终态回执共用的持久账本；默认 `data/terminal-receipts.db` |
| `GROK_ROUTINE_URL` / `GROK_ROUTINE_KEY` / `GROK_ALLOWED_HOST` | 已授权 Grok routine 的 HTTPS 地址、秘密和精确主机白名单；见 [终态回执](TERMINAL_RECEIPTS.zh.md) |

Events 的数据库与允许主机是 CLI 参数 `--events-db` / `--event-host`，不是环境变量。非默认外部 HTTPS 地址通过 `--public-url` 声明，仍不改变 loopback 监听。

launchd 模板只含 `ROUNDTABLE_HOME`，不继承终端的 `export`。使用前需本地渲染路径，并为每个服务单独配置所需环境；需要代理时，在 server 和 MCP 的环境中都加入 `ROUNDTABLE_OUTBOUND_PROXY`。模板默认 `RunAtLoad=false`、`KeepAlive=false`，不会自动加载或启用 Events；本次文档步骤不要求加载它们。不要把真实秘密或渲染后的配置提交到仓库。

## 用户一次性验收清单

以下步骤由用户在自己的账号和已授权环境中完成。替换占位符；保留原任务与账本，不通过删除账本或重建任务掩盖不确定结果。

1. **核对已有实例**：首次安装准备专用端口/数据库；已有实例先核对归属并备份。仅在需要更新配置时于维护窗口停止确认管理的对应进程，禁止多个实例共用数据库；不要无故重启健康的 server。
2. **选择出站方式并启动新进程**：仅在需要代理时，在 server/routine 与 MCP 网关环境中分别设置 `ROUNDTABLE_OUTBOUND_PROXY=http://127.0.0.1:<PORT>`；直连安装不设置显式代理，并避免继承意外的 ambient proxy。再启动已配置的新实例。已运行进程不会读取后来在终端设置的变量；修改配置后需在用户自己的维护窗口重启相应进程。
3. **doctor**：使用成员环境运行 `.venv/bin/python scripts/check.py doctor`。确认 `outbound_local` 和 `outbound_backend` 均为 `configured=true`；显式代理安装的 `mode` 应为 `trusted_proxy_dns`，直连安装应为 `direct_public_ip_pinning`。这里的 `outbound_backend` 是结构化对象；该结果不证明厂商回调可达，也不验证独立网关环境。
4. **工具发现**：完成已授权的私有 Tunnel 配置，在 ChatGPT connector 选择 **No authentication**。在真实 Dot 会话发现工具，调用 `list_rooms` / `list_bots` 核对唯一预期群与成员；不能只看 Tunnel doctor 成功。
5. **批准 callback hostname**：核对产品实际提供的回调主机名，按前文为网关设置精确 `--event-host` 与私有 `--events-db`。不要用通配符或关闭主机校验；必要时只重启自己管理的网关。
6. **allowance**：管理员在授权范围内运行 `.venv/bin/python scripts/admin.py allowance '<ROOM_ID>' '<ORIGIN_AGENT_ID>' 1`。管理员凭据不进入 Bot 配置。
7. **订阅 `handoff.available`**：由用户在 Dot 明确要求监听本成员任务，确认订阅成功。订阅有期限，不是永久授权；事件仅用于唤醒。
8. **原生 roundtrip**：在入口成员环境执行 [回环指南](ROUNDTRIP.zh.md) 的 `roundtrip --worker '<WORKER_AGENT_ID>'`，观察真实 Dot 被唤醒、领取并回传 nonce，入口取得同一任务结果。用 `doctor --evidence` 回读，分别记录协议关联、原生对话和唤醒观察；只读回环不创建 Codex 任务，也不发送 Grok routine。

若任一步失败，记录对应阶段和安全错误码，修复后从原任务状态继续。真实工作交接与可选 Grok 终态回执需要另行明确范围；本清单不替代这些授权或验收。

## 排障、备份与撤销访问

| 症状 | 下一步 |
|---|---|
| 端口已占用 | 用系统进程/监听检查确认归属；复用健康实例或在维护窗口停自己的旧实例，不 kill 不明程序；改端口时同步 URL、gateway 和 profile |
| `field server_url not found` | 更新本地 profile 为模板的 `server_urls` 列表 |
| `tunnel_authorization_mismatch` | 核对 gateway 与 Tunnel 使用同一完整 scoped Bearer、ChatGPT No authentication，检查 forwarded Authorization 覆盖；不输出值、不关闭认证 |
| 本机可达但控制面失败 | 核对 Tunnel key 有效期/Read+Use、组织/workspace、控制面显式代理、运行时健康；不要把模型 key 或改 Clash 当修复 |
| 工具有但事件来源缺失 | 确认网关声明 Events，再用既有插件“刷新工具”，刷新当前会话的来源/schema；不创建重复插件 |
| 创建订阅报错 | 先核是否已有订阅，再区分平台校验、精确 host 拒绝或 challenge；没有真实 host 就停止，不猜 URL |
| 机器恢复后未收到事件 | 核对三个进程、代理、key、订阅到期及原任务状态；新订阅不保证重放过去事件 |

备份包含任务 DB、Events DB、必要配置及秘密管理器恢复信息，使用加密、仅操作者可读的离线/受控存储；不上传到 GitHub、聊天或公开 artifact。活跃 SQLite 不可只复制主 `.db` 文件而忽略 WAL：使用一致的 SQLite 在线备份流程，或在计划维护窗口优雅停止相应写入者后备份。恢复前避免多个进程共用同一数据库，保留原任务和不确定发送账本。

停用此接入时，先取消产品内的事件 automation/订阅并确认不再续订，再断开/卸载目标 ChatGPT 插件；核对归属后停止专用 Tunnel/MCP 进程。只撤销专用 runtime key 和目标 Tunnel/workspace 访问，不影响其他应用共享的资源。需同时撤销本机成员能力时，在管理员界面移除该成员并更新网关授权；仅停止 Tunnel 不撤销已泄露的成员 token。保留受保护的数据备份；永久删除数据需另行决定。不要直接删除整个 `data/` 或全局 key/组织。共享 server 如仍用于其他成员应继续运行。

托管 `up` 默认提供绑定本实例的临时 macOS 防睡眠，支持 `--no-caffeinate` 关闭和经核验的进程状态。手工 `start-local.sh` 不变；请阅读[AC/合盖/网络限制](SETUP_AUTOMATION.zh.md)，不修改持久电源设置。
