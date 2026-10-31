# 架构与状态机

浏览器 → loopback HTTP 服务 → Store / SQLite → 单任务 mailbox → bot / 受信桥接程序 → 关联 reply → 下一任务。

- `server.py`：HTTP 输入限制、管理员/room/agent 认证边界、静态页面、每 0.5 秒 demo 调度。
- `roundtable.py`：SQLite 持久化与 RLock 串行事务；创建房间、讨论、任务；来源标签由服务端身份决定。
- `grok_adapter.py`：可选单次 outbound routine 调用，不接管状态机，不生成虚假 completion。
- `static/`：无外部 CDN、框架和构建链；token 只留在页面内存，内容用 textContent。

## 调度与幂等

每次讨论唯一 `(room, request_id)`，固定 targets/budget。创建人类消息后只生成一个 pending job。成功回调在同一数据库事务中标记 job、写入 bot 消息、递增 turn、生成下一 job 或完成。相同 job 相同回复去重；冲突拒绝。DB 与 RLock 保护并发回调不会多推进一轮。API 不承诺多进程部署安全。

```
run: running → completed | stopped | timeout | failed | interrupted
job: pending → done | stopped | timeout | failed | interrupted
```

达到 budget 完成；失败与超时停止整场讨论，避免自动重试花费或无限反馈。停止与回调竞争时由事务顺序决定：若回调先完成，其已提交消息保留；stop 会取消下一 pending job。重启终止所有未完成 run/job。没有自动恢复不确定外部动作。

Mailbox 是 at-least-once 可读任务；对结果使用幂等提交，不声称外部执行 exactly-once。桥接程序必须保存其 dispatch 状态，网络异常后不能盲目重发。Grok CLI 为显式单次发送，操作人负责去重；不会自动消费 mailbox。

## 信任边界

管理员只能创建房间，房间控制 token 不会发送给 bot。Agent token 只读取本房间本讨论中分配给它的 job，并回复其 job。Bot 不可伪造 sender/source、选择下一发言者、启动讨论或调用 shell。与 bot 对话的内容本身不可信，即使标记为 bot 来源也不授予工具权限。

每个新讨论仅携带用户在本房间提交的议题及该讨论已有的 bot 回复。例子、测试均使用人工编写的合成内容；不包含开发会话或真实用户数据。

本地停止只是 relay 停止，外部 Bot 的执行取消需要其自己的官方机制。未实现 remote gateway；公开部署必须另行设计 TLS、入口认证、代理策略、配额、超时、令牌撤销和数据库运维。
