# 有界等待与只读回环

先安全配置已授权成员环境：`ROUNDTABLE_URL`（仅 loopback）、
`ROUNDTABLE_ROOM`、`ROUNDTABLE_AGENT`、`ROUNDTABLE_TOKEN`。不要把秘密粘贴到
命令或聊天；这些命令不解析秘密文件。

```sh
"${ROUNDTABLE_HOME}/.venv/bin/python" "${ROUNDTABLE_HOME}/local_client.py" wait TASK_ID --timeout 600
"${ROUNDTABLE_HOME}/.venv/bin/python" "${ROUNDTABLE_HOME}/local_client.py" roundtrip --worker dot --timeout 600 --evidence "${ROUNDTABLE_HOME}/data/roundtrip.json"
"${ROUNDTABLE_HOME}/.venv/bin/python" "${ROUNDTABLE_HOME}/local_client.py" doctor --evidence "${ROUNDTABLE_HOME}/data/roundtrip.json"
```

将 `TASK_ID` 和 `dot` 替换为授权任务及已注册成员 ID。`roundtrip` 是显式写操作：
创建一个只返回 nonce 的只读 assignment，派发预算 1、任务期限取自 `--timeout`（默认 600，范围 30–86400 整秒），入口身份需
1 次发起额度。它本身不订阅、不唤醒厂商。接收者须已获得执行该测试的授权，
只返回原样 nonce，不执行命令、读取文件或创建 Codex 工作。

`wait` 轮询终态，本地等待超时不取消任务。整个等待使用单调时钟总预算，覆盖 DNS、连接及持续缓慢传输的响应；
到期中断活动 socket。无法中断的 DNS 调用在结束前保留四个受限 worker 槽之一；
容量耗尽时明确失败，不继续增加后台线程。回环超时会保留私有、
原子写入的证据，状态为 unknown。应查看原任务，避免盲目重复创建。成功时输出任务、
assignment ID 及截断结果摘要。合成 worker 使用 `--test`。证据不保存 lease 或凭据。

Doctor 核对证据的群与成员范围，并重新读取认证后的任务和 assignment。完成状态与
预期结果摘要匹配仅证明协议关联，不证明厂商身份。失败、超时、未知、范围不符或
不可用证据不能证明成功。证据是本机可编辑的操作人数据，不是签名审计记录。

原生和唤醒验收分别使用可选的**操作人声明**。亲自观察原生会话，以及独立观察
事件唤醒后，可在证据 JSON 增加 `operator_observations.native_roundtrip` 和/或
`operator_observations.wake`。每项包含 `confirmed: true`、`source: "operator"`、
相同 `task_id` 与 `assignment_id`，以及协议观测之后、非未来的有限 Unix 时间
`observed_at`。只有非测试、结果关联且完成的证据才接受这些声明。Doctor 明确标注
为本机操作人声明，仍保持 `vendor_identity_verified: false`。不要把合成测试标成
原生成功。

运行隔离契约回归（无实际 Grok/dot 账号）：

```sh
cd "${ROUNDTABLE_HOME}"
.venv/bin/python -m unittest discover -s tests -p test_roundtrip.py -v
```

测试使用临时 loopback 端口、真实 HTTP MCP SDK 初始化/工具调用、Events 订阅与
challenge 的注入 mock callback，以及模拟 Dot worker 的领取、进度和完成回报。
它验证协议，不证明真实厂商投递或原生唤醒。
