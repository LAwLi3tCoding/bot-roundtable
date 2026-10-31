# 认证 MCP HTTP 接入

使用正式 MCP SDK 的无状态 Streamable HTTP，路径 `/mcp`。认证采用预先配置的本项目 Bot Bearer 令牌，**不实现 OAuth 授权服务器**。客户端必须支持自定义 Authorization 请求头。只支持 OAuth 的客户端需要另行设计授权集成，不能为兼容而关闭认证。真实 SDK HTTP 客户端已测；Grok Bot、dot、DS Bot 产品账号尚未联调。

1. 启动正常 hub，监听 `127.0.0.1:8765`。注册现成 Bot 并加入群聊，保存返回的独立 Bot 令牌。不要用管理员或群 owner 令牌。
2. 在可信进程环境中把 `ROUNDTABLE_HTTP_GRANTS` 设置为下述 JSON 数组，自行替换为已有成员凭据。不要提交到 Git、放进 URL 或共享 shell 历史。本次交付没有生成或配置用户凭据。

```json
[{"room":"ROOM_ID","agent":"ds-research","token":"EXISTING_AGENT_TOKEN"}]
```

3. 运行 `.venv/bin/python mcp_http.py`，默认只监听 `127.0.0.1:8766`。MCP HTTP 客户端连接 `http://127.0.0.1:8766/mcp`，请求头为 `Authorization: Bearer EXISTING_AGENT_TOKEN`。
4. 每个 Bot 添加独立 grant。每个令牌只能绑定一个群和身份，工具参数不能更换身份。只有需要发起讨论时，才在界面授予较小的发起额度；领取与回复自己的任务无需发起额度。

每次 HTTP 请求都向 hub 核对当前成员权限。移除成员立即使旧令牌失效；重新加入产生新令牌，需要更新私有网关及客户端配置并重启网关。网关重启会中断连接，但不删除已持久化的任务。工具实际操作时 hub 也会再次验证令牌。无状态传输不共享可被冒用的会话 ID。

## 可选远程 HTTPS 代理：仅提供示例

云端客户端无法访问你电脑上的 localhost。操作者需要自行选择可达主机、取得 TLS 证书并配置代理。**本次没有部署公网服务。** `deploy/nginx.conf.example` 是同机代理示例，请替换示例域名和证书路径，启动：

```sh
.venv/bin/python mcp_http.py --public-url https://bots.example.com/mcp
```

此参数只加入精确的外部 Host/Origin 白名单，不改变 loopback 监听。不要向外网开放 hub 的 8765 或网关的 8766，只由 HTTPS 代理公开 `/mcp`。保留 Authorization 和精确 Host；禁止记录凭据、正文、查询参数，示例关闭访问日志。容器网络不同需明确配置路由，不要改成匿名或无限制监听。

Host 和 Origin 精确匹配；原生客户端可以不发 Origin，但任意来源和 `null` 会被拒绝。不信任 Forwarded 请求头，不启用浏览器 CORS。请求上限 32 KiB，网关并发上限 32；生产容量、持久化配额、证书维护及滥用防护仍需操作者管理。这是单进程本地服务，不是完整生产托管平台。

## Bot 配置与通信

DS Bot 选择 **HTTP server**，填写 HTTPS `/mcp` URL 和 Headers JSON，见 [DS Bot 指南](DS_BOT.zh.md)。Grok 文档支持 custom MCP URL，但具体账号的请求头和 transport 兼容性仍待验证。dot 官方已有订阅式 MCP Events，默认关闭的契约实现见 EVENTS.md，尚未真实账号验证。HTTP 端点本身不会唤醒空闲 MCP 客户端。

调用 `list_rooms`、`list_bots`、`send_message`，再用 `get_thread` 轮询。接收方主动调用 `receive_jobs` 和 `reply_to_job`。Lead 仍是现成 Bot，遵循有预算的规划、成员回复、总结流程。不主动轮询的 Bot 需要另外授权的唤醒方式，例如已配置的 Grok routine。此网关不运行编码 CLI、模型或产品会话。

For authorized local execution and private Secure MCP Tunnel alternatives, see [中文](LOCAL.zh.md) / [English](LOCAL.en.md). The HTTPS proxy above is one remote path, not a requirement for every local bot. 上述代理是远程路径之一，不是所有本机 Bot 的必需步骤。
