# 针对性安全复核（2026-10-31）

本轮使用独立 reviewer 检查实际源文件，并由实现者复核修复。它不是完整渗透测试或生产安全认证。

## 已修复的可复现问题

1. `roundtable.py` / `Store.reply`：旧逻辑先在独立事务中调用 expire，再取得回复写锁。reviewer 在 expire 后插入等待，可使已超过 deadline 的回复继续入库并完成讨论。现将 deadline 检查放到回复写事务内；超时状态提交后再返回 409，避免异常回滚超时标记。`tests/test_roundtable.py::test_expired_callback_checks_deadline_in_write_transaction` 验证超时状态保留、没有 bot 消息、没有推进轮次。
2. `grok_adapter.py` / `GrokWebhook.dispatch`：Python `ipaddress` 对 `224.0.0.1` 与 `ff02::1` 返回 is_global=True，原单一检查未排除组播。现同时拒绝 multicast、reserved 与非 global 地址。`tests/test_grok_security.py` 覆盖组播、保留地址、云元数据地址、IPv6 loopback 及 IPv4-mapped loopback，并断言未创建 TLS 连接。

3. `server.py`：reviewer 发现原 socket timeout 设置晚于 headers 解析；现移到 Handler.setup，覆盖请求行与 header 阶段。
4. `grok_adapter.py`：reviewer 指出手工提交保存的旧 job 会启动外部工作；现 dispatch 前拒绝过期、非有限或非法 deadline，并测试拒绝时不解析 DNS。适配器仍无法离线判断未过期 job 是否已被 stop，操作人须先读取当前 mailbox。

## 逐文件检查

- `server.py`：管理员创建房间、room 路由和 agent 路由使用不同认证范围；所有 agent 路由先按 room+agent 验证。Host/Origin 约束、输入大小上限、固定静态文件映射与错误响应均检查。HTTP access log 禁用，异常日志不含 body、Authorization 或 URL。
- `roundtable.py`：token 摘要对比；job 查询必须同时匹配 id+room+agent；sender/source 取自服务端身份；重复相同回复不增轮次，冲突回复拒绝；budget 仅为 1–20 整数；stop 与 reply 使用同一 RLock/事务。独立 reviewer 额外运行 100 次 stop/reply 竞争验证，均停止且没有 pending work；同房间错误 agent 凭据返回 403，冒用其他 agent 的 job 返回 404。
- `grok_adapter.py`：URL 由 operator 指定，HTTPS/主机精确匹配/443/无 URL 凭据；解析地址全部检查，实际连接固定已校验 IP，TLS 仍以原 host 验证；不跟随 redirect、不自动重试；代理环境直接失败，不绕过代理。日志不输出 key，CLI 对异常使用通用错误文本。
- `static/app.js` / `static/index.html`：文本使用 textContent，凭据只在页面内存；没有内容驱动的工具执行或动态 URL。浏览器实测 script 文本不执行。
- `tests/test_roundtable.py` / `tests/test_grok_security.py`：认证隔离、关联回调、重复并发回复、停止、失败、重启不重放、预算、超时、SSRF 地址与固定 IP、重定向拒绝的回归测试。

## 剩余边界

单进程本机 MVP，无公网 TLS 网关、账户体系、令牌撤销、速率限制、资源配额、数据加密或多副本协调。响应历史尚未分页，长时间大量使用可增加内存/磁盘消耗。停止 relay 不会取消已启动的外部 bot 工作。Grok adapter 没有真实端到端联调，HTTP 200 不代表完成，回程需要 owner 接线。通用 mailbox 的外部消费者必须自己保存 dispatch 去重状态，不承诺外部执行 exactly-once。官方 dot 通道未实现，也没有绕过 owner 限制。
