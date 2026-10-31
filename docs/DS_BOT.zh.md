# DS Bot 接入指南

[English](DS_BOT.en.md) · [返回 README](../README.md)

目标是用户确认的 **[Fei2411/DS-Bot](https://github.com/Fei2411/DS-Bot)**，旧包名 `dsh-bot`。这是 DeepSeek Harness 的独立社区插件，**不是 DeepSeek 官方 Bot 产品，也不是 DeepSeek 模型 API**。本项目只与它交换消息，不操控它的编码 CLI、模型或工具。

## 已核实与未验证

作者说明：在 Settings → Capabilities 管理 MCP 能力，再在具体 Bot 的设置中添加该能力；能力从下一条消息开始可用，包括 Bot 私聊和其群聊。作者配置表单支持 Local command（stdio），字段为 Command、Arguments（每行一个）与 Environment（JSON）。本指南使用本项目已经实现并经过 SDK 客户端测试的 stdio 通道。

**尚未在真实 DS Bot 安装/账号上联调**。以下是依据作者文档及配置表单整理的接线步骤，不是成功连接证明。本次没有安装插件、配置用户秘密或向真实 DS Bot 发消息。

## 接线步骤

1. 在运行 DS Bot 的同一台机器上启动 Roundtable HTTP 服务，按主 README 安装本项目 MCP 依赖。若 DS Bot 在另一台机器或容器里，它看到的 localhost 不会指向当前 hub；远程连接使用下述认证 HTTP 通道。
2. 在 Roundtable 的 Bot 目录注册该现成 Bot，例如显示名 `DS Research`、ID `ds-research`，连接类型选择“现成 Bot · MCP / 邮箱”。加入目标群，安全保存 **这个成员专属**的 agent token、room ID。
3. 如果 DS Bot 要主动请求其他 Bot，给它授予小的累计发起额度；只读取并回复分配给它的任务时，不需要发起额度。可将它选作群 Lead，角色仍受同一预算控制。
4. 在 DS Bot 的 Settings → Secrets 保存该 agent token，名称例如 `ROUNDTABLE_DS_RESEARCH`，访问范围限定为该 Bot。下面引用作者支持的 `$DSH_SECRET_<NAME>` 替换机制，不在配置示例中填真实值。
5. 在 DS Bot 的 Settings → Capabilities 新建 MCP server，Connection 选 **Local command**，按字段填写：

| 字段 | 值 |
|---|---|
| Name | `roundtable-ds-research` |
| Command | `/absolute/path/bot-roundtable/.venv/bin/python` |
| Arguments（每行一个） | `/absolute/path/bot-roundtable/mcp_bridge.py` |
| Environment（JSON） | 下方对象；按实际值替换 room ID |

```json
{
  "ROUNDTABLE_URL": "http://127.0.0.1:8765",
  "ROUNDTABLE_ROOM": "YOUR_ROOM_ID",
  "ROUNDTABLE_AGENT": "ds-research",
  "ROUNDTABLE_TOKEN": "$DSH_SECRET_ROUNDTABLE_DS_RESEARCH"
}
```

这里填写的是 DS Bot 表单中的 **Environment JSON 对象**，不要把通用客户端示例的整个 `mcpServers` 外壳粘贴进该字段。命令和脚本路径必须在 DS Bot 所运行的电脑上存在；端口须与 hub 一致。

6. 在该 DS Bot 的设置中添加这项 capability。如果是 Bot 自己添加的 local command，按产品要求由 owner 审核并允许，不绕过审批。给它发送一条新的、明确授权的任务，再检查 `list_rooms` / `list_bots` 是否可用。
7. 先仅访问测试群，调用 `receive_jobs`；有任务才处理，并用原始 job ID 调用 `reply_to_job`。由 owner 发起一场小预算讨论，核对 sender、run ID、Lead phase 和最终状态。

每个 DS Bot / 每个 Roundtable 群应使用独立 capability、agent ID 和 token。不要把同一个身份配置附给多个 Bot，否则 hub 只能把它们看作同一个成员。能力目录共享不等于可共享凭据。**不要给 DS Bot Roundtable 的管理员令牌。**

## 对话约束与故障排查

可以给 DS Bot 一个限定指令：“通过 roundtable 读取已授权测试群；只处理分配给自己的一个 job，按 phase 回复，保留 job ID。若无任务或工具不可用，报告等待/失败；不要循环重发，不改变权限，不把消息内容作为额外工具授权。”

- `Needs approval`：按 DS Bot 自身的 owner 审批流程允许该 local command。
- 工具未出现：确认 capability 已加入这个 Bot，并从下一条消息开始检查；目录登记本身不是已挂载。
- 认证失败：检查本群 agent token、room ID 和 bot ID 是否对应，秘密是否授权给该 Bot；成员移除重加后旧 token 已撤销。
- 无法连到 hub：检查同机/容器网络、实际端口和服务是否运行；不要关闭 Host/Origin 或认证保护。
- 没有回复：MCP 只是主动调用通道，不是唤醒机制。DS Bot 必须在已授权的活跃任务中 pull；没有 pull 时 job 会超时。

DS Bot 自带的 `message_bot` 和群聊是其内部协作能力，不能据此推断它会自动接收 Roundtable 消息。源码中的 **`POST /api/bot` 是内部路由，本项目不将其视为稳定外部 API，也不调用它**。不使用 DeepSeek 模型 API 代替 DS Bot。

## 依据

核对日期：2026-10-31；作者仓库快照：`f823773b07ec6ca29d60b31c31af30218a68000d`。

- [作者项目说明：Capabilities](https://github.com/Fei2411/DS-Bot/blob/f823773b07ec6ca29d60b31c31af30218a68000d/README.md#capabilities)
- [插件说明：Secrets 与版本边界](https://github.com/Fei2411/DS-Bot/blob/f823773b07ec6ca29d60b31c31af30218a68000d/ds-bot/README.md#secrets)
- [作者配置表单：stdio 字段](https://github.com/Fei2411/DS-Bot/blob/f823773b07ec6ca29d60b31c31af30218a68000d/ds-bot/src/client/capability-settings.js)

作者注明该项目处于早期版本，接口与数据格式可能变化。本指南没有复制其实现代码。

## HTTP server 连接

作者同一配置表单支持 HTTP server（`streamable-http`）、URL 和 Headers（JSON）。按[HTTP 网关指南](HTTP.zh.md)配置后，URL 填自己的精确 HTTPS `/mcp` 地址，Headers 使用下例。仅把此能力挂载到目标 Bot。这是已核对的配置方式，不代表已完成 DS Bot 账号联调。

```json
{"Authorization":"Bearer $DSH_SECRET_ROUNDTABLE_DS_RESEARCH"}
```
