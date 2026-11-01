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

Events 仍须明确配置并经授权订阅。`ROUNDTABLE_EVENT_TIMEOUT` 控制含 DNS 与传输在内的回调总期限，默认 20 秒，范围 0.01–120。Mac 回调约 7 秒是用户观察，非本项目实测。普通代理环境变量仍默认拒绝；明确使用可信 HTTP CONNECT 代理时设置 `ROUNDTABLE_EVENT_PROXY` 为 HTTP origin，不支持代理凭据。回调 DNS 全部结果必须为公网地址，CONNECT 使用已校验 IP，TLS 与 Host 保留原回调域名。不跟随重定向或回退直连。不可中断 DNS 在结束前继续占用有界工作槽位。主机拒绝日志仅含 `callback_host_not_approved` 和清理过的 hostname。

另行批准订阅后，`handoff.available` 流程为 receive_assignments → claim_assignment → dot 核对任务及用户权限，通过自身已连接电脑工具创建 Codex 任务 → report progress → completed/failed。事件只是唤醒提示，不是新增授权；任务文本不能越过已批准的范围。
