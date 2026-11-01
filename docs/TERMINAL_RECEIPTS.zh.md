# 可选 Grok 终态回执

这是操作人显式运行的命令，不是默认启用的服务钩子；它不创建 routine 或订阅。
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
指定任务；最后一次 HTTP 请求可能额外增加客户端网络超时时间。
尚未终结就不预留、不发送。支持 `completed`、`failed`、`timeout`、`cancelled`；
外发正文只有 `task_id` 和 `status`，不带指令、结果、令牌或 lease。
复用 Grok 传输的 HTTPS 主机批准、公网 DNS 校验、固定 IP、TLS 验证及禁止代理、
禁止重定向保护。HTTP 200 只说明 routine 接受请求。

SQLite 持久账本在网络发送之前，为每个群/任务原子预留**一次尝试**；共享同一账本
的并发进程和重启后命令不会重复发送。重读终态或状态再次变化都不重发。
异常记为 `uncertain`，不会自动重试。预留后发送前崩溃可能丢回执，远端接受后崩溃
可能留下本机未知结果。这是至多一次尝试，**不是精确一次投递**；即使发送前网络
检查失败也消耗预留。重启应保留同一账本，删除或另选账本可能重复发送。
不要通过换账本重试不确定结果；请先自行检查原生 routine 历史再作决定。

这不会启动 Codex、派发任务，也不构成 Grok 原生身份验证；mock 测试只验证协议和
本机去重语义。
