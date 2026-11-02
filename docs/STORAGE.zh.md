# 状态、日志、迁移与清理

代码和私有状态现在各自保存。`ROUNDTABLE_HOME` 仍指**代码 checkout**，不能用作状态目录。旧 checkout 的 `data/` 迁移或备份前，不要运行 `git clean -xfd`、删除或重新 clone：Git 忽略文件不代表 clean 不会永久删除它们。

## 默认位置

实例默认名称为 `default`。托管命令接受 `--name <INSTANCE_NAME>`，独立命令可通过 `ROUNDTABLE_INSTANCE_NAME` 选择同一名称。名称限字母、数字、`_`、`-`，首字符须为字母或数字，最多 64 字符。

| 平台 | 默认状态目录 | 默认托管日志 |
| --- | --- | --- |
| macOS | `~/Library/Application Support/bot-roundtable/<INSTANCE_NAME>` | `~/Library/Logs/bot-roundtable/<INSTANCE_NAME>` |
| Linux | `${XDG_STATE_HOME:-~/.local/state}/bot-roundtable/<INSTANCE_NAME>` | `<STATE_DIRECTORY>/logs` |
| Windows | `%LOCALAPPDATA%\bot-roundtable\<INSTANCE_NAME>` | `<STATE_DIRECTORY>\logs`（不支持 Windows 托管进程管理） |

托管状态优先级：**`--state-dir` > `ROUNDTABLE_STATE_DIR` > 平台默认**。显式自定义状态目录的日志位于 `<STATE_DIRECTORY>/logs`，macOS 也如此。XDG_STATE_HOME 必须为绝对路径；Windows 要求 LOCALAPPDATA。不自动修复权限，不修改全局环境或系统安全设置。POSIX 目录 0700、普通文件与 FIFO 0600；Windows 管理员持久凭据使用当前用户 ACL 校验，路径解析支持不代表 Windows 全部运行时已支持。

```sh
.venv/bin/python scripts/local_runtime.py paths --name demo
.venv/bin/python scripts/setup-local.py --name demo --allowance 1
sh scripts/up.sh --name demo --without-tunnel
.venv/bin/python scripts/local_runtime.py status --name demo
```

`paths` 显示将使用的解析路径，不显示凭据。每条命令保持相同实例名称或显式状态目录。首次默认 setup 发现旧 checkout 的 `data/local` 时，会拒绝静默创建替代身份；请明确迁移，或明确选择另一个新实例。Status/doctor 会提示状态位于仓库内、macOS Documents/Desktop/Downloads/iCloud 位置、代码位于这些保护位置及发现旧目录。旧目录检测只看是否存在，不读取秘密内容。这些是位置告警，不是 TCC 权限探测；状态移出 Documents 不会免除仍放在其中的代码所受后台运行限制。

## 文件清单与权限

| 文件 | 用途 | 保护与备份处理 |
| --- | --- | --- |
| `admin.json`（旧 `admin.env`）、`room.env`、`<member>.env` | 管理员、群 owner、独立成员凭据 | 0600；加密/离线私有备份，禁止上传 |
| `runtime-key.env`、`routine.json`、`routine.pending.json` | Tunnel key、已批准/待批准 routine 配置 | 0600；保留权限、有效期与撤销责任 |
| `roundtable.db`、`events.db`、`terminal.db` | 任务历史、订阅/签名秘密、最多一次回执 ledger | 0600；停机/checkpoint 后备份，数据库与 ledger 一起保留 |
| `instance.json`、`tunnel.yaml`、`roundtrip.json` | 身份/schema、scoped profile 引用、证据 | 0600；即使 profile 引用本身安全，整个状态目录仍私有 |
| `incomplete.json`、`recovery.json`、`prepared.json` | 初始化中断恢复，可能含凭据 | 0600；离线检查，不自动迁移 |
| `.lock`、`.admin.lock`、组件 `*.pid.json` / `*.started.json` / `*.child.json` / `*.stop.json`、`health.url`、`tunnel-child.pid`、`tunnel-log.pipe` | 生命周期协调、临时健康/FIFO 通道 | 0600；不能靠复制这些文件转移进程归属 |
| `<LOG_DIRECTORY>/<component>.log[.1–.3]`、`*.log.lock` | 过滤后的有界状态日志、单写者锁 | 0600；未知厂商文本丢弃，不记录原始 HTTP/body |
| `launchd/*.plist` | 可选且尚未加载的 launchd 模板 | 0600；不含秘密，另行加载前审阅 |

托管日志默认**每文件 10 MiB、三个备份**，另加当前文件。首次 setup 用 `--log-max-bytes <BYTES>`（256–1 GiB）、`--log-backups <COUNT>`（1–20）配置。重复 setup 不修改已有设置；已有停机实例需明确编辑私有 `instance.json` 中这些非秘密数字字段。每个 supervisor 在整个写入/轮转期间持有独占日志锁，第二写者失败而不竞争。Tunnel FIFO 通过同一有界写入器处理，受控关闭时删除。过长记录丢弃；崩溃可能留下旧 FIFO，启动会检查归属/类型后替换。

Setup 未指定 `--server-port`/`--mcp-port` 时选择两个不同的可用 loopback 端口，保存到 `instance.json`、成员 URL 和 profile；status/doctor 显示实际 loopback URL。这是探测，不是一直保留端口：启动前被其他进程抢占时，启动明确拒绝，不接管或杀掉该进程。请复核配置或明确初始化另一独立实例。独立手工启动仍默认 8765/8766 以兼容旧用法，自动选端口仅用于托管 setup。

## 手工转移已停止的实例

项目不提供自动迁移或导入命令。旧布局由操作者审核并做一次性转移，没有脚本解释或重写旧凭据。旧 `data/` 未完成私有备份校验前，不要运行 `git clean -xfd`。

1. 用原管理器停止源实例，并防止 launchd/登录任务重启它；确认 server、MCP、Tunnel 及后代进程均停止。不要复制正在写入的 SQLite 数据库。
2. 完整托管 `down` 验证停止及归属后，对私有 `*.db` 执行 `PRAGMA wal_checkpoint(TRUNCATE)`，包括任务、Events 和回执库。它需要 `lsof`，拒绝仍打开的数据库；缺失时需另行安装。单组件停止不执行 checkpoint。旧管理器或独立 server 则由操作者用 SQLite 维护工具对已停止源的每个库 checkpoint、关闭连接并确认没有 `-wal`；遇 busy 或不确定应停下调查，绝不能删除 WAL 来强行成功。
3. 复制到新的空私有目标，保留 POSIX 0700 目录/0600 文件或经审核的 Windows 当前用户 ACL。拒绝符号链接、特殊文件或不安全归属。管理员、群/成员凭据、数据库、原回执 ledger 和已批准配置一起保留；不得把 PID/started/child/stop/health/FIFO 瞬态文件复制成新进程归属。按需单独保留私有日志，项目不执行日志搬迁。
4. 在有意修改配置前，逐个校验普通文件大小和 SHA-256。清单保持私有，不打印凭据内容。审核旧 schema、绝对路径、日志目录、代码位置及 profile 引用；不同 JSON/env 旧布局没有自动转换。Keyring 引用绑定路径，需要另行审核系统凭据处理，不能盲目复制元数据。
5. 保留 callback 审批、代理和回执历史，不扩大权限。回执历史缺失或不确定时，在核对前保持终态通知关闭，不能清空 ledger 重发旧任务。禁止新旧副本同时运行。`rebind` 仅用于兼容托管配置的代码目录搬家，不转换旧布局。
6. 明确验证新配置与限定范围访问，验收前保留旧目录及备份，之后单独决定清理。项目不会替你删除原目录或执行这次转移。

## 代码搬家与稳定启动入口

状态 schema 与 checkout 位置分开校验。移动/重新 clone 后指定同一状态目录，`up` 会报 `code_location_changed_run_rebind`，不会丢状态或启动第二实例。确认原实例停止后：

```sh
.venv/bin/python scripts/local_runtime.py rebind --name demo
sh scripts/render-launchd.sh --name demo --output '<NEW_PRIVATE_REVIEW_DIRECTORY>'
# 可选指定私有输出目录：--output '<REVIEW_DIRECTORY>'
```

Rebind 检查已停状态后只更新代码位置，不改凭据或网络审批。Render 默认输出 `<STATE_DIRECTORY>/launchd`，拒绝覆盖已有文件，重渲染请选择新审阅目录。Plist 使用 `/bin/sh <CHECKOUT>/scripts/up.sh`，包装脚本解析当前 `.venv/bin/python`（或明确提供的 `ROUNDTABLE_PYTHON`）。**同一路径**重建 venv 不需重新渲染；移动 checkout 仍需 rebind、重新审阅/替换 plist。不会自动加载 launchd，identity label 与 Homebrew/系统 PATH 保留。

独立 `server.py` 和 `start-local.sh server` 默认 `<STATE_DIRECTORY>/manual/roundtable.db`，`local_client.py` 证据默认 `<STATE_DIRECTORY>/roundtrip.json`，回执命令默认 `<STATE_DIRECTORY>/terminal-receipts.db`，不依赖 cwd。显式 `--db`、`--evidence`、`--ledger` 及对应环境变量优先。独立管理员文件默认在选定数据库旁的 `admin-credentials`，可用 `--admin-state` 覆盖。独立 `admin_credentials.py` CLI 同样默认 `<STATE_DIRECTORY>/manual/admin-credentials`；若 server 使用自定义数据库，须给该 CLI 的 `--state-dir` 明确传入实际管理员目录。不能让独立和托管管理器共用一个数据库。

## 备份与卸载

用实例自己的管理器停机并确认清理状态，再对状态目录和单独配置的日志制作一致私有副本。一起保留权限、数据库、回执 ledger、keyring 恢复能力；不要上传 Git、聊天或公开 artifacts。Keyring 引用本身不包含系统秘密，不能当独立完整备份。

卸载时只停止该实例，另行禁用自己曾安装的 launchd/登录任务，取消真实平台订阅，并通过已批准的账号控制撤销其 Tunnel/runtime key 和 Bot 凭据。确认是否保留私有历史后，才明确删除该实例状态/日志目录。删除代码或状态不会撤销远端 key，也不会删除系统 keyring 条目。脚本不执行账号撤销、递归清理、系统电源修改或自动加载/卸载 launchd。
