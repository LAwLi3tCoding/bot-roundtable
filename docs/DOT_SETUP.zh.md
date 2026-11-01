# dot 私有交接配置

这里只提供待操作人审核的模板，不安装客户端、不加载 launchd、不创建密钥、不订阅 Events、不发送 routine。

1. 选择独立 checkout，把 `ROUNDTABLE_HOME` 设置为其绝对路径。用 Python 3.12/3.13 创建 `.venv` 并安装 `requirements.lock`。按 README 通过已批准的秘密管理器/环境提供管理员凭据，创建专用群；Grok 和 dot 使用独立成员凭据，发起额度先保持 0。秘密不得放入命令正文、源码或聊天。
2. 在管理员环境中运行 `sh scripts/start-local.sh server`，仅绑定 loopback。已有实例占用端口或数据库时不得重复启动。
3. 通过安全环境引用设置 dot 的 `ROUNDTABLE_URL`、`ROUNDTABLE_ROOM`、`ROUNDTABLE_AGENT`、`ROUNDTABLE_TOKEN`。执行 `.venv/bin/python scripts/check.py doctor` 和 `probe`。包装器不打开秘密文件、关闭 stdin、总时限 15 秒；成功仅证明传输。
4. 按 `docs/HTTP.zh.md` 设置只包含目标 dot 成员的 `ROUNDTABLE_HTTP_GRANTS`。安全设置 `ROUNDTABLE_TUNNEL_AUTH_HEADER` 为完整的 `Bearer <dot scoped token>`，网关用它限制固定身份。执行 `sh scripts/start-local.sh mcp`，默认仅本机 8766。
5. 另行授权后只从官方取得 tunnel 客户端，自行提供 runtime key、tunnel ID 和 workspace 权限。审核并复制 `examples/tunnel-client.yaml` 为命名 profile；设置 `ROUNDTABLE_TUNNEL_PROFILE`，执行官方 `tunnel-client doctor --profile <name> --explain`，获得授权后才运行 tunnel 启动脚本。
6. 此私有固定身份路线在 ChatGPT connector 选择 **No authentication**，由 tunnel 注入本地 Bearer；网关认证仍然开启。官方[配置参考](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)明确 forwarded connector headers 最后应用，大小写不敏感地覆盖 `mcp.extra_headers`。发生 Authorization 冲突或缺失时，本网关返回 `tunnel_authorization_mismatch`，不记录值。禁止关闭认证凑通。值相同无法区分注入与转发，必须从真实 connector 调用 `list_rooms`/`list_bots` 核对唯一群和身份；doctor 不代表端到端验收。
7. 用户批准后才给入口小额额度：在管理员环境执行 `.venv/bin/python scripts/admin.py allowance <room-id> <origin-agent> 1`。不得把管理员 token 给 Bot。订阅、原生 Codex 执行、routine 配置分别受用户授权范围限制。

`deploy/launchd/` 模板默认不运行。`${ROUNDTABLE_HOME}` 是渲染占位符，launchd 不会自动展开；本地替换为绝对路径、安全注入环境（含官方 tunnel 二进制 PATH）、审核权限和生命周期，获得批准后才加载。不得把秘密粘贴到 tracked plist。前台进程用 Ctrl-C 停止，管理的后台进程先核对归属再发信号。模板不配置自动重启。

## 租约与回调运行参数

`claim_assignment(..., lease_seconds=60)` 接受 30–1800 的整数；租约和进度续期均不超过任务截止时间，进度按所选租约时长续期。任务 `timeout_seconds` 范围为 30–86400。过期后可在次数与预算范围内重新领取，旧租约不能继续报告。外部 Codex 操作不会自动撤销或重放。

Events 仍须明确配置并经授权订阅。`ROUNDTABLE_EVENT_TIMEOUT` 控制含 DNS 与传输在内的回调总期限，默认 20 秒，范围 0.01–120。未设置显式代理时，普通代理环境变量触发失败关闭；明确使用可信 HTTP CONNECT 代理时设置 `ROUNDTABLE_OUTBOUND_PROXY`（兼容 `ROUNDTABLE_EVENT_PROXY`）为 HTTP origin，不支持代理凭据。直连时回调 DNS 全部结果必须为公网地址并固定所选 IP；显式代理时 CONNECT 使用规范化域名，由可信代理解析，TLS 与 Host 保留该域名。不跟随重定向或回退直连。不可中断 DNS 在结束前继续占用有界工作槽位。主机拒绝日志仅含 `callback_host_not_approved` 和清理过的 hostname。

另行批准订阅后，`handoff.available` 流程为 receive_assignments → claim_assignment → dot 核对任务及用户权限，通过自身已连接电脑工具创建 Codex 任务 → report progress → completed/failed。事件只是唤醒提示，不是新增授权；任务文本不能越过已批准的范围。

配置获得批准后，可显式启用 Events 入口：

```sh
sh scripts/start-local.sh mcp --events-db "${ROUNDTABLE_HOME}/data/events.db" --event-host approved.hostname
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
| `ROUNDTABLE_TUNNEL_PROFILE` | `start-local.sh tunnel` 必需；已审核的本地 profile 名称 |
| `ROUNDTABLE_EVIDENCE` | 本机客户端默认回环证据路径；默认 `data/roundtrip.json`，可由 `--evidence` 覆盖 |
| `ROUNDTABLE_TERMINAL_NOTIFICATIONS` | 仅值 `1` 启用 server 终态工作器，默认关闭 |
| `ROUNDTABLE_TERMINAL_ROOM` / `ROUNDTABLE_TERMINAL_ORIGIN` | 终态工作器限定的群与当前入口成员 |
| `ROUNDTABLE_TERMINAL_LEDGER` | 手动及自动终态回执共用的持久账本；默认 `data/terminal-receipts.db` |
| `GROK_ROUTINE_URL` / `GROK_ROUTINE_KEY` / `GROK_ALLOWED_HOST` | 已授权 Grok routine 的 HTTPS 地址、秘密和精确主机白名单；见 [终态回执](TERMINAL_RECEIPTS.zh.md) |

Events 的数据库与允许主机是 CLI 参数 `--events-db` / `--event-host`，不是环境变量。非默认外部 HTTPS 地址通过 `--public-url` 声明，仍不改变 loopback 监听。

launchd 模板只含 `ROUNDTABLE_HOME`，不继承终端的 `export`。使用前需本地渲染路径，并为每个服务单独配置所需环境；需要代理时，在 server 和 MCP 的环境中都加入 `ROUNDTABLE_OUTBOUND_PROXY`。模板默认 `RunAtLoad=false`、`KeepAlive=false`，不会自动加载或启用 Events；本次文档步骤不要求加载它们。不要把真实秘密或渲染后的配置提交到仓库。

## 用户一次性验收清单

以下步骤由用户在自己的账号和已授权环境中完成。替换占位符；保留原任务与账本，不通过删除账本或重建任务掩盖不确定结果。

1. **停旧起新**：先核对旧实例的归属、端口和数据库，备份数据；只停止自己确认管理的旧进程。按当前版本准备新进程配置，禁止多个实例共用数据库。不要停止来源不明的服务。
2. **设置代理并启动新进程**：在 server/routine 与 MCP 网关环境中分别设置 `ROUNDTABLE_OUTBOUND_PROXY=http://127.0.0.1:<PORT>`，再启动已配置的新实例。已运行进程不会读取后来在终端设置的变量；修改配置后需在用户自己的维护窗口重启相应进程。
3. **doctor**：使用成员环境运行 `.venv/bin/python scripts/check.py doctor`。确认 `outbound_local.mode` 和 `outbound_backend.mode` 均为 `trusted_proxy_dns`，且 `configured=true`。这里的 `outbound_backend` 是结构化对象；该结果不证明厂商回调可达，也不验证独立网关环境。
4. **工具发现**：完成已授权的私有 Tunnel 配置，在 ChatGPT connector 选择 **No authentication**。在真实 Dot 会话发现工具，调用 `list_rooms` / `list_bots` 核对唯一预期群与成员；不能只看 Tunnel doctor 成功。
5. **批准 callback hostname**：核对产品实际提供的回调主机名，按前文为网关设置精确 `--event-host` 与私有 `--events-db`。不要用通配符或关闭主机校验；必要时只重启自己管理的网关。
6. **allowance**：管理员在授权范围内运行 `.venv/bin/python scripts/admin.py allowance '<ROOM_ID>' '<ORIGIN_AGENT_ID>' 1`。管理员凭据不进入 Bot 配置。
7. **订阅 `handoff.available`**：由用户在 Dot 明确要求监听本成员任务，确认订阅成功。订阅有期限，不是永久授权；事件仅用于唤醒。
8. **原生 roundtrip**：在入口成员环境执行 [回环指南](ROUNDTRIP.zh.md) 的 `roundtrip --worker '<WORKER_AGENT_ID>'`，观察真实 Dot 被唤醒、领取并回传 nonce，入口取得同一任务结果。用 `doctor --evidence` 回读，分别记录协议关联、原生对话和唤醒观察；只读回环不创建 Codex 任务，也不发送 Grok routine。

若任一步失败，记录对应阶段和安全错误码，修复后从原任务状态继续。真实工作交接与可选 Grok 终态回执需要另行明确范围；本清单不替代这些授权或验收。
