# 可选 Grok 终态回执

隔离托管实例请见[自动配置](SETUP_AUTOMATION.zh.md)：setup-local 创建独立 origin/worker 凭据，up/down/status 核验进程归属，owner doctor 不向成员暴露跨群数据。下述手工环境方式仍支持。


自动服务钩子默认关闭，也提供下方操作人显式运行的命令；它不创建 routine 或订阅。
请自行配置 routine 并明确授权使用。通过可信秘密管理器继承
`ROUNDTABLE_URL`、`ROUNDTABLE_ROOM`、`ROUNDTABLE_AGENT`、`ROUNDTABLE_TOKEN`
以及 `GROK_ROUTINE_URL`、`GROK_ROUTINE_KEY`、`GROK_ALLOWED_HOST`。
脚本不解析凭据文件。秘密不要放在命令参数、仓库或聊天里。

```sh
"${ROUNDTABLE_HOME}/.venv/bin/python" "${ROUNDTABLE_HOME}/terminal_receipts.py" \
  TASK_ID --dispatch-terminal --wait 600 \
  --ledger "${ROUNDTABLE_HOME}/data/terminal-receipts.db"
```

`--wait` 默认 0，上限 86400 秒。命令通过已有认证 loopback 客户端，约每秒查询
指定任务，使用客户端 wait 实现限制总等待时间。
尚未终结就不预留、不发送。支持 `completed`、`failed`、`timeout`、`cancelled`；
外发正文只有 `task_id` 和 `status`，不带指令、结果、令牌或 lease。
复用 Grok 传输的 HTTPS 主机批准与 TLS 验证；直连模式校验公网 DNS 并固定 IP，显式代理模式信任代理解析并使用域名 CONNECT。两种模式均禁止重定向。HTTP 200 只说明 routine 接受请求。

SQLite 持久账本在网络发送之前，为每个群/任务原子预留**一次尝试**；共享同一账本
的并发进程和重启后命令不会重复发送。重读终态或状态再次变化都不重发。
异常记为 `uncertain`，不会自动重试。预留后发送前崩溃可能丢回执，远端接受后崩溃
可能留下本机未知结果。这是至多一次尝试，**不是精确一次投递**；一旦预留，明确的网络失败也保留记录，不自动重试；发送不确定同样保留预留。重启应保留同一账本，删除或另选账本可能重复发送。
不要通过换账本重试不确定结果；请先自行检查原生 routine 历史再作决定。

这不会启动 Codex、派发任务，也不构成 Grok 原生身份验证；mock 测试只验证协议和
本机去重语义。

## 自动服务钩子（显式启用）

在启动新的 `server.py` 进程前，通过可信操作人配置继承以下设置。不要隐式重载或
修改已有服务：

```sh
export ROUNDTABLE_TERMINAL_NOTIFICATIONS=1
export ROUNDTABLE_TERMINAL_ROOM=YOUR_TEST_ROOM_ID
export ROUNDTABLE_TERMINAL_ORIGIN=grok-origin
export ROUNDTABLE_TERMINAL_LEDGER="${ROUNDTABLE_HOME}/data/terminal-receipts.db"
# GROK_ROUTINE_URL / GROK_ROUTINE_KEY / GROK_ALLOWED_HOST 由秘密管理器提供
"${ROUNDTABLE_HOME}/.venv/bin/python" "${ROUNDTABLE_HOME}/server.py"
```

指定 origin 必须是当前群成员。只选择属于该群、origin 为 `bot:<origin>` 且成员
epoch 仍有效的任务。后台线程使用独立只读数据库连接观察已提交的终态事件。
首次启用保存最新事件游标，跳过此前已终结的历史任务；已在运行及未来任务在进入
终态后可以通知。游标持久保存，首次启用后的停机期间事件在重启后会被观察。
必须保留同一账本；换账本会重置游标与发送预留。任务失败后重试不再产生第二条
回执。成员与状态在选择时校验；选择后才撤销权限无法撤回已经开始的网络操作。

服务在接受请求前启动线程，退出等待最多一秒。网络发送不持有 Store 锁或 SQLite
事务。每次发送总等待上限 20 秒（包括 DNS），最多四个传输线程；卡住的 DNS 或
socket 调用占住名额直到结束。超时或容量耗尽消耗预留、记为不确定且不重试。
超时和线程停止会取消真实 Grok 传输并关闭其跟踪的 socket。DNS、TCP、TLS 后的
取消检查阻止这些阶段解除阻塞后才发出的迟到 POST；已发送的请求无法撤回，远端
是否接受仍不确定。这些限制保证本机服务可响应。下次进程启动前设启用标志为
`0` 即关闭；未设置时不启动线程，也不解析 routine 配置。

两种模式都读取 `ROUNDTABLE_TERMINAL_LEDGER`，默认使用工作目录下的
`data/terminal-receipts.db`。自动和手动模式应指定同一账本的绝对路径。

回执预检发生在账本预留之前：缺少显式代理或代理配置无效时标为 `definitely_not_sent`，不消耗发送次数，worker 游标保持待处理。网络结果不确定仍保留预留且永不重放。暂态 worker 故障通过可停止的 0.1 至 30 秒指数退避恢复；认证 doctor capabilities 显示 `terminal_worker` 状态、原因码、重试秒数和 `outbound_backend` 模式，不包含 URL 或秘密。账本通过排他创建 0600 文件及 0700 新目录保护，不改变全局 umask，不覆盖旧数据或放宽已有权限。

托管实例用 `sh scripts/set-grok-routine.sh` 隐藏输入 URL/key，保存私有显式 opt-in；仅下次 server 启动启用 worker，不自动重启。精确 host 从已验证 HTTPS URL 推导，样例文件不启用外发。参阅[官方 routine](https://cursor.com/help/grok-bot/routines)、[用量/价格](https://x.ai/bot)及[安全回执提示词](PROMPTS.zh.md)。
