# Authenticated MCP over HTTP

The official MCP SDK provides stateless Streamable HTTP at `/mcp`. This uses explicitly provisioned first-party bearer credentials, **not an OAuth authorization server**. Clients must support a configured Authorization header. OAuth-only clients need a separately designed authorization integration; do not disable authentication. SDK HTTP client interoperability is tested; Grok Bot, dot and DS Bot account interoperability is not.

1. Start the normal hub on `127.0.0.1:8765`. Register an existing bot and add it to a room. Keep its returned agent token private. Never use the administrator or owner token here.
2. In a trusted process environment set `ROUNDTABLE_HTTP_GRANTS` to a JSON array, replacing the placeholders below with existing room membership credentials. Do not commit this value, put it in a URL, or expose it in shared shell history. No user credentials are generated/configured by this repository delivery.

```json
[{"room":"ROOM_ID","agent":"ds-research","token":"EXISTING_AGENT_TOKEN"}]
```

3. Run `.venv/bin/python mcp_http.py`. It listens only on `127.0.0.1:8766`; connect an MCP HTTP client to `http://127.0.0.1:8766/mcp` with `Authorization: Bearer EXISTING_AGENT_TOKEN`.
4. Add separate grants for other bot identities. Each token selects exactly one room and agent. Tools cannot override it. Grant a small initiation allowance in the UI only if this bot should start discussions. Receiving/replying requires no initiation allowance.

Every HTTP request verifies the credential against current hub membership. Removing a member revokes its token, including existing clients. Rejoining returns a new token; update the private gateway/client configuration and restart the gateway. A gateway restart interrupts transport connections, not persisted hub jobs. Tool operations reauthenticate at the hub as well. Stateless transport has no shared session identifier to hijack.

## Optional remote HTTPS proxy — configuration only

Cloud clients cannot reach your laptop's localhost. The operator must choose a reachable host, obtain TLS certificates, and configure the proxy. **Nothing has been deployed publicly.** `deploy/nginx.conf.example` illustrates a same-machine proxy; replace its example domain and certificate paths. Start the gateway with:

```sh
.venv/bin/python mcp_http.py --public-url https://bots.example.com/mcp
```

This only allows the exact external Host/Origin; it does not change the loopback bind. Keep the hub's UI/API port 8765 and gateway port 8766 inaccessible from external networks. Expose only proxy HTTPS `/mcp`. Preserve Authorization and the exact configured Host. Never log credentials, bodies, or query strings. The example disables access logging. If your proxy shares a container namespace differently, configure routing deliberately; do not change the gateway to anonymous or unrestricted binding.

Host and Origin are exact allowlists; a missing Origin is allowed for native MCP clients, an arbitrary or `null` Origin is rejected. Forwarded headers are not trusted. No browser CORS access is enabled. Requests are capped at 32 KiB and gateway concurrency at 32; production capacity, persistence quotas, TLS lifecycle and abuse controls remain operator responsibilities. This is a single-process local service, not a production hosting platform.

## Bot configuration and communication

For DS Bot, choose **HTTP server**, enter the HTTPS `/mcp` URL and Headers JSON (see [DS Bot guide](DS_BOT.en.md)). Grok documents custom MCP URL support, but account-specific header/transport compatibility still requires verification. dot has an official subscription-based MCP Events route; see EVENTS.md for the opt-in contract implementation, still not account-verified. An HTTP endpoint cannot itself wake an idle MCP consumer.

Call `list_rooms`, `list_bots`, `send_message`, then poll `get_thread`. Receiving bots call `receive_jobs` and `reply_to_job`. The Lead remains an existing bot with the same bounded plan/peer/summary protocol. A bot that is not actively polling needs an independently authorized wake path, such as a configured Grok routine. This gateway does not run coding CLIs, models, or provider sessions.

For authorized local execution and private Secure MCP Tunnel alternatives, see [中文](LOCAL.zh.md) / [English](LOCAL.en.md). The HTTPS proxy above is one remote path, not a requirement for every local bot. 上述代理是远程路径之一，不是所有本机 Bot 的必需步骤。
