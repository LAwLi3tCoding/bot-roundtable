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

Setup 持久保存管理员、群 owner（`room.env`）及独立成员凭据，使用私有权限，重复 setup 不替换已有值。不要把群 owner 凭据交给 Bot。macOS/Linux 的 `ui` 要求本管理器拥有的服务已健康运行，通过 `open`/`xdg-open` 打开一次性登录链接。签发请求必须携带管理员认证；随机登录码有效 60 秒，位于 URL fragment，页面在交换前立即清除。登录码单次使用，并有数量和速率上限；交换要求实际 IPv4 loopback 对端、精确 Host 与同源 Origin。换得的会话有效一小时且不可续期，仅允许群和任务操作，不允许凭据、成员权限或登录码管理。短期会话只进入 sessionStorage，手工粘贴也不能持久记住。长期管理员令牌不进入链接、输出或启动器参数。短期登录码仍是秘密，浏览器或系统 URL 记录可能短暂保留，勿分享链接。服务重启会使内存中的登录码和会话失效。

需要主动复制长期令牌时使用 `.venv/bin/python scripts/local_runtime.py ui --copy-token`：macOS 使用 `pbcopy`，Linux 优先 `wl-copy`、其次 `xclip`，Windows 使用 `clip.exe`。令牌通过 stdin 传递，不打印；没有工具时仅提示私有凭据记录位置，请使用可信本地凭据管理器。Windows 尚不支持托管自动登录与进程管理。剪贴板管理器或同步可能保留令牌，用完请清除。Setup 不操作剪贴板。

随后修改生成 profile 中非秘密的 Tunnel ID，运行 `sh scripts/save-runtime-key.sh`、`sh scripts/up.sh` 和 `.venv/bin/python scripts/local_runtime.py doctor`。隐藏输入 runtime key 需要终端。完整 `up` 会在启动组件前明确检查 `runtime_key_missing`、`tunnel_client_not_found`、`tunnel_id_placeholder`；`--without-tunnel` 有意跳过 Tunnel 检查。未知失败仅显示类别和异常类型，不输出异常原文。语法有效不代表 key 的实际权限或有效期正确。

## 持久管理员凭据

单独运行 `server.py` 时，会在数据库旁的 `admin-credentials/admin.json`（默认数据库为 `<STATE_DIRECTORY>/manual/roundtable.db`，与托管状态分开） 创建并复用私有凭据；可用 `--admin-state '<PRIVATE_DIRECTORY>'` 指定位置。托管实例保存在自身状态目录。不要每次启动重新生成环境令牌。显式提供的 `ROUNDTABLE_ADMIN_TOKEN` 仅覆盖当前进程使用值，不会改写持久值。Doctor 以 `admin_environment_override_active` 提示覆盖状态，不显示值。

默认使用 POSIX 0700 目录、0600 文件。Windows 管理员凭据持久化使用仅当前用户 ACL，写入前检查，无法保护或权限不安全时拒绝落盘；Windows 托管进程管理尚不支持。Setup 的 `--keyring` 或独立 server 的 `--admin-keyring` 可选优先使用已安装的系统后端（macOS Keychain、Linux Secret Service、Windows Credential Manager）。如需使用，请自行安装配置可选 `keyring` 包，参阅[官方文档](https://keyring.readthedocs.io/en/latest/)。未知或明文后端不受信任。首次创建找不到支持的后端时退回安全文件；已有 keyring 身份无法读取时拒绝继续，不会静默重新生成。Keyring 写入失败也不会静默降级。Keyring 元数据绑定状态路径。请保留该路径，或由管理员明确审核系统凭据转移；只复制元数据不是受支持的凭据转移。独立 server 可保留原 --admin-state 路径。

只停止准备轮换的实例，移除环境覆盖后运行：

```sh
.venv/bin/python scripts/local_runtime.py rotate-admin-token
# 独立 server 的替代命令：先停止该独立 server
.venv/bin/python admin_credentials.py rotate-admin-token --state-dir '<ADMIN_STATE_DIRECTORY>'
```

轮换不打印新令牌。重启该实例后生效，macOS 可通过 `ui` 重新连接。群和成员 token 不受影响，浏览器旧访问需另行清除。私有备份离线保存，禁止上传 Git 或聊天。新凭据记录安全发布后，轮换会删除旧 keyring 条目。删除失败时返回 `old_keyring_entry=failed_manual_cleanup_required`：新凭据已提交，旧条目需通过系统凭据管理器清理；不会回滚或打印秘密。撤销环境覆盖还需更新其外部秘密来源。

## 浏览器保存与任务可见性

仅精确 `127.0.0.1` 来源默认使用 `sessionStorage`：同一标签页刷新会自动连接并进入上次仍有权限访问的群。**记住本机**默认关闭；勾选后使用 `localStorage`，跨浏览器重启保留，并自动连接上次仍可访问的群。取消勾选会移除持久副本并改用 session storage。**忘记已保存的访问凭据**清除内存及两种存储、密码框，并使尚未完成的认证响应失效；还会尝试撤销短期 UI 会话；若请求失败或页面先关闭，会话可能继续有效至到期或服务重启。它不会撤销长期管理员或成员凭据。恢复时无效的凭据会被丢弃。浏览器禁止存储时仍可仅内存连接。其他主机名不持久保存令牌。

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

## 手工转移状态与待审批 routine

项目不再提供自动旧实例导入或状态迁移命令。请遵循[手工存储清单](STORAGE.zh.md)：停机、checkpoint、私有复制、校验并保留原目录。不同旧布局由操作者审核，不自动猜测或替换凭据。

明确准备好的私有 `routine.pending.json` 可在实例停止时通过 `.venv/bin/python scripts/local_runtime.py approve-routine` 批准。文件的 `environment` 对象必须且只能包含 `GROK_ROUTINE_URL`、`GROK_ROUTINE_KEY`、`GROK_ALLOWED_HOST`。先私下核实目标及权限，不将秘密贴入命令或聊天。命令验证 HTTPS 与精确域名，拒绝覆盖已有活跃 routine，保存明确批准但不发送请求。下次 `up` 可启用终态回执，因此切换前必须保留原 receipt ledger 并处理旧的不确定发送历史。新批准配置也可用隐藏输入的 `set-grok-routine.sh`。

生成的 launchd plist 包含 Homebrew 与系统标准 PATH，不含凭据值，也不会自动加载。输出目录必须私有，不会静默放宽权限。原生系统 keyring 与 Windows ACL 仍需各平台验收；合成测试不代表真实厂商或跨平台端到端成功。

## 补回缺失的群凭据文件

重复 setup 或 `repair-room-env` 会先尝试从匹配的私有恢复记录补回 `room.env`。数据库 hash 无法还原原令牌。若原值已丢失，先停止实例，再明确运行 `.venv/bin/python scripts/local_runtime.py repair-room-env --rotate-room-token`：它撤销旧群 owner token、保留成员 token，并写入新的私有文件。私有 `room-token.pending.env` 用于轮换中断恢复，需保留且禁止发布。Setup 不会静默轮换。
