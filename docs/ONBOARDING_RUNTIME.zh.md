# 本机接入与凭据恢复

配合[本地自动配置指南](SETUP_AUTOMATION.zh.md)使用。账号配置、精确 callback 审批、订阅续期和厂商权限仍需人工完成。本页描述产品能力，不代表允许迁移或轮换现有安装。

## 初始化并打开网页

在 `${ROUNDTABLE_HOME}` 中使用已安装依赖的 `.venv`。默认使用[仓库外的平台状态目录](STORAGE.zh.md)；自定义时，每条命令都带同一个 `--state-dir '<PRIVATE_INSTANCE_DIRECTORY>'`。

```sh
.venv/bin/python scripts/setup-local.py --origin grok --worker dot --allowance 1 \
  --server-port '<SERVER_PORT>' --mcp-port '<MCP_PORT>'
sh scripts/up.sh --without-tunnel
.venv/bin/python scripts/local_runtime.py ui
```

Setup 持久保存管理员凭据、`room.env`（群 ID 与群 owner token）、独立成员文件，均使用私有权限。重复执行已成功的 setup 不会重新生成凭据。`room.env` 具有群 owner 权限，不应交给 Bot。`ui` 要求本管理器拥有的服务已健康运行；macOS 上通过 stdin 将管理员令牌交给 `pbcopy`，仅打开固定 `http://127.0.0.1:<SERVER_PORT>`，不将令牌放入参数、输出或 URL。请粘贴到本机网页密码框，用完清空剪贴板；剪贴板管理器和跨设备同步可能保留内容。其他平台只显示不含令牌的说明，请使用已批准的本地凭据管理器。Setup 本身不操作剪贴板。

随后修改生成 profile 中非秘密的 Tunnel ID，运行 `sh scripts/save-runtime-key.sh`、`sh scripts/up.sh` 和 `.venv/bin/python scripts/local_runtime.py doctor`。隐藏输入 runtime key 需要终端。完整 `up` 会在启动组件前明确检查 `runtime_key_missing`、`tunnel_client_not_found`、`tunnel_id_placeholder`；`--without-tunnel` 有意跳过 Tunnel 检查。未知失败仅显示类别和异常类型，不输出异常原文。语法有效不代表 key 的实际权限或有效期正确。

## 持久管理员凭据

单独运行 `server.py` 时，会在数据库旁的 `admin-credentials/admin.json` 创建并复用私有凭据；可用 `--admin-state '<PRIVATE_DIRECTORY>'` 指定位置。托管实例保存在自身状态目录。不要每次启动重新生成环境令牌。显式提供的 `ROUNDTABLE_ADMIN_TOKEN` 仅覆盖当前进程使用值，不会改写持久值。

默认使用 POSIX 0700 目录、0600 文件。Windows 管理员凭据持久化使用仅当前用户 ACL，写入前检查，无法保护或权限不安全时拒绝落盘；Windows 托管进程管理尚不支持。Setup 的 `--keyring` 或独立 server 的 `--admin-keyring` 可选优先使用已安装的系统后端（macOS Keychain、Linux Secret Service、Windows Credential Manager）。如需使用，请自行安装配置可选 `keyring` 包，参阅[官方文档](https://keyring.readthedocs.io/en/latest/)。未知或明文后端不受信任。首次创建找不到支持的后端时退回安全文件；已有 keyring 身份无法读取时拒绝继续，不会静默重新生成。Keyring 写入失败也不会静默降级。Keyring 元数据初始绑定状态路径，托管实例可使用 [migrate-state](STORAGE.zh.md) 保留对原系统条目的验证后引用；独立 server 应保留原 --admin-state 路径，或另行明确迁移凭据，不应手工移动元数据。

只停止准备轮换的实例，移除环境覆盖后运行：

```sh
.venv/bin/python scripts/local_runtime.py rotate-admin-token
# 独立 server 的替代命令：先停止该独立 server
.venv/bin/python admin_credentials.py rotate-admin-token --state-dir '<ADMIN_STATE_DIRECTORY>'
```

轮换不打印新令牌。重启该实例后生效，macOS 可通过 `ui` 重新连接。群和成员 token 不受影响，浏览器旧访问需另行清除。私有备份离线保存，禁止上传 Git 或聊天。Keyring 轮换可能保留旧版本条目；确认恢复正常后才通过系统凭据管理器清理。撤销环境覆盖还需更新其外部秘密来源。

## 浏览器保存与任务可见性

仅精确 `127.0.0.1` 来源默认使用 `sessionStorage`：同一标签页刷新可恢复。**记住本机**默认关闭；勾选后使用 `localStorage`，跨浏览器重启保留。取消勾选会移除持久副本并改用 session storage。**忘记已保存的访问凭据**清除内存及两种存储、密码框，并使尚未完成的认证响应失效；不会撤销服务端凭据。恢复时无效的凭据会被丢弃。浏览器禁止存储时仍可仅内存连接。其他主机名不持久保存令牌。

存储按来源（包括端口）隔离，但不是秘密保险箱：同源脚本、扩展、浏览器配置备份或使用同一配置的其他人可能读取。浏览器会话恢复或复制标签页也可能保留 session storage，用完请点忘记。请使用私有可信浏览器配置，共用设备不要勾选记住。

群里已有任务但没有讨论消息时，首次默认打开**任务与交接**。手动选择讨论后，轮询不会强制切回。生命周期详情保留在已有任务视图，不额外生成可能包含 lease 或 token 的系统群消息。

## Grok 无需 source 凭据即可派任务

托管 client 只读取 origin 成员文件，不使用管理员或群 owner token。Setup 使用其他 worker 名称时替换示例中的 ID；Bot 仍需自身已授权的本机执行权限。

```sh
.venv/bin/python scripts/local_runtime.py client --operation create <<'JSON'
{"title":"Read-only check","context":"Use only authorized project context.","assignments":[{"worker":"dot","instruction":"Report current project status without making changes."}],"budget":1,"timeout_seconds":600,"request_id":"read-only-check-001"}
JSON
.venv/bin/python scripts/local_runtime.py client --operation tasks
.venv/bin/python scripts/local_runtime.py client --operation inbox
```

Create 要求 JSON stdin，最多 32 KiB、读取总期限两秒；终端或卡住的管道会失败，不无限等待。`create`、`tasks`、`inbox` 拒绝 `--task-id`/`--body`。Inbox 是 origin 自己的收件箱，不是其他成员。相同 request ID 和内容复用已有任务；只有确实新任务才使用新 ID。任务正文不扩权。任务已接受不代表厂商已被唤醒或已完成工作。

## 导入旧实例快照

请明确准备**已停止写入、私有、离线的旧实例快照**，不要指向正在运行的服务。导入器只读取已知文件，不执行或 source 文本，不修改源目录，不启动服务，拒绝非空目标。秘密始终保持私有。支持普通 `KEY=VALUE` 和 `export KEY=VALUE`（可带引号）；拒绝 shell 展开、命令替换和重复键。

```sh
.venv/bin/python scripts/local_runtime.py import-legacy \
  --from '<PRIVATE_OLD_SNAPSHOT>' --state-dir '<NEW_EMPTY_PRIVATE_DIRECTORY>' \
  --origin grok --worker dot --server-port '<NEW_SERVER_PORT>' --mcp-port '<NEW_MCP_PORT>'
```

支持的输入清单：

- `admin.json` 的 `token` 或 `admin_token`，或 `admin.env` 的 `ROUNDTABLE_ADMIN_TOKEN`；仅 keyring 元数据不能导出秘密。
- `room.json` 的 `id`/`room_id` 和 `token`/`room_token`，或 `room.env` 的 `ROUNDTABLE_ROOM`、`ROUNDTABLE_ROOM_TOKEN`。缺少群 owner 凭据必须由操作者恢复，导入不会编造替代值。
- 各 `<agent>.json` 的 `id`/`agent_id`、`room`/`room_id`、`token`，或 `<agent>.env` 的 `ROUNDTABLE_AGENT`、`ROUNDTABLE_ROOM`、`ROUNDTABLE_TOKEN`。必须属于同一群。用 `--origin`/`--worker` 指定旧成员名称；已有 `instance.json` 则采用其中名称。
- 可选 `runtime-key.env`、`tunnel/runtime-key.env` 或 `tunnel/key.env` 中的 `CONTROL_PLANE_API_KEY`；可选 `tunnel.yaml` 或 `tunnel/roundtable.yaml` 仅提供标量 `control_plane.tunnel_id`。新 profile 使用安全环境引用及新端口重新生成，不解释任意 YAML tag/alias。
- 可选 `events.env` 的已明确批准 `ROUNDTABLE_EVENT_HOST`、`ROUNDTABLE_OUTBOUND_PROXY`，或托管 `instance.json` 配置。`--proxy` 只覆盖导入实例。这是保留操作者原审批，不推断新域名。
- 可选 `grok-routine.json` 的 `url`/`endpoint`、`key`，或 `routine.json` 中的 `environment` 对象。验证 HTTPS 与主机规则后保存为 `routine.pending.json`，**不启用**；后续真实外发前，通过 `set-grok-routine.sh --state-dir ...` 明确重新输入已批准值。
- 可选已停止并 checkpoint 的 `roundtable.db` 快照，保留本地历史并验证群及成员 token hash。存在 `-wal` 或 `-journal` 时拒绝，应先制作一致离线备份。没有数据库则只重建身份，额度为零且无历史，所需额度应另行明确授予。

不克隆 Events 订阅或旧回执 ledger。新 ledger 永久禁止所有导入任务的回执（包括仍在进行的任务），因为其旧发送历史未知；只有新任务可产生新回执，请保留此新 ledger，避免不确定发送重放。切换前核对已有平台订阅和旧实例停机；导入不会撤销旧凭据。普通异常会清理私有 staging，目标仍为空；进程突然崩溃可能留下私有 `.import-*`，应离线检查，不发布或自动采用。

生成的 launchd plist 包含 Homebrew 与系统标准 PATH，不含凭据值，也不会自动加载。输出目录必须私有，不会静默放宽权限。原生系统 keyring 与 Windows ACL 仍需各平台验收；合成测试不代表真实厂商或跨平台端到端成功。
