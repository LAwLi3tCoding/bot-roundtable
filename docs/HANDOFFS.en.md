# Native bot delegation and handoffs

[中文](HANDOFFS.zh.md) · [Quick start](../README.en.md)

Start in Grok Bot or another existing bot, delegate distinct instructions to other room members through MCP, inspect the same `task_id` and individual handoff threads on the Web, then poll the structured results from the active originating bot. The hub never runs models, coding CLIs, or the bots' tools, and does not fabricate an AI summary.

## Local first run

Start the server as described in the README, create a room with both demo members, and choose **Delegate task**. Enter a title, explicitly shared context, and a separate instruction for each member. Switch between Overview and individual handoffs to see progress and results. Deterministic demo workers claim assignments and produce `[DEMO]` text; this proves the communication flow, not real provider connectivity.

The Web can also inspect native MCP tasks, append shared or worker-specific context, retry failed handoffs, and cancel a task. Context is inert data: it does not restart completed work or expand authority. Cancelling a failed task prevents retry; cancellation propagates through descendants but cannot undo external side effects.

## First real pairing: Grok Bot + dot

1. Register separate existing Grok and dot identities, join them to one room, and grant the originating member a small initiation allowance. Registration is not a connection. Keep separate agent credentials; never give a bot admin or room-owner credentials.
2. Configure the supported MCP connection in each product: stdio or authenticated Streamable HTTP. A cloud client cannot reach another computer's localhost. An operator must provide a reachable HTTPS endpoint and compatible authentication; see the [HTTP guide](HTTP.en.md). This project has not deployed one and does not implement an OAuth authorization server.
3. **Direct dot MCP attachment and real account interoperability remain unverified.** The owner must explicitly initiate a bounded task in dot and first verify that its environment supports this connection. If it cannot, report it as disconnected; do not substitute a CLI or model API. No public automatic dot wake endpoint has been verified.
4. Once both connections actually work and both bots are active: origin calls `create_task`; worker calls `receive_assignments`, `claim_assignment`, and `report_assignment`; origin polls `get_task`. Without an active reader, work remains queued or expires. MCP does not wake an idle bot or automatically return control to a sleeping origin.

Grok routine webhooks are a possible optional wake path; HTTP 200 means accepted, not completed. The existing `grok_adapter.py` implements the older discussion **job** protocol and is **not automatically wired to new assignment dispatch**. No routine was configured, called, or tested end to end. [DS Bot configuration](DS_BOT.en.md) remains available; installing it is not required for this pairing.

A shared product connector token proves possession, not strong isolation between the product's internal bots. Use independent connections and minimum permissions where the product supports them; otherwise treat the connector as a shared principal.

## Tools and flow

The original seven discussion tools remain; nine new tools bring the total to sixteen:

| Tool | Purpose |
|---|---|
| `create_task` | Title, shared context, distinct `{worker,instruction}` entries and request_id; returns task_id immediately |
| `list_tasks` | Latest 100 visible tasks; not full-history pagination |
| `get_task(task_id, after)` | Status, structured results and cursor-based events; cursor / has_more |
| `receive_assignments` | Own queued/working handoffs, never another worker's private instruction |
| `claim_assignment` | task_id, assignment_id, expected_attempt, request_id; returns temporary lease / attempt |
| `report_assignment` | Own lease / attempt; progress renews lease, completed / failed closes attempt |
| `add_task_context` | Origin/owner adds shared or assignment-specific context without execution |
| `retry_assignment` | Origin/owner requeues failed work within budget, allowance and attempt limits |
| `cancel_task` | Origin/owner cancels task and descendants |

Example arguments (replace IDs with members of your own room; no credentials):

```json
{
  "title": "Review the release plan",
  "context": "Use only the plan explicitly provided for this task.",
  "assignments": [
    {"worker": "dot-reviewer", "instruction": "Identify omissions and risks."},
    {"worker": "another-member", "instruction": "Independently check acceptance criteria."}
  ],
  "budget": 4,
  "timeout_seconds": 600,
  "request_id": "caller-generated-unique-key"
}
```

With only Grok and dot present, Grok assigns **one** handoff to dot. Multiple workers require additional real members or explicitly labelled demos. The coordinator cannot assign itself. It may also be the room Lead: task mode supports this while preserving the original discussion's Lead self-initiation guard.

Workers claim using the assignment's current `attempt` as `expected_attempt`. Keep the returned temporary lease and report only under that worker's identity. New semantic operations use new request IDs; transport retries reuse the same ID and identical arguments. Continue fetching events while `has_more` is true. All assignments must complete for the task to be completed; once all are terminal, any failure makes it failed. The active origin can summarize these structured results in its own native conversation; the hub supplies no replacement model.

## Persistence, permissions and limits

- `tasks`: room, authenticated origin/coordinator, parent/root, depth, budget and deadline. `assignments`: independent instructions, membership epoch, status, attempt, lease hash, results and text artifacts. `task_events`: audit events. `task_receipts`: idempotent responses.
- 1–6 distinct workers per task, no self-dispatch, at most 20 active tasks per room. A 1–20 dispatch budget reserves initial assignments on creation; every subsequent claim spends another slot. Bot initiation allowance is cumulative across tasks and old discussions, never refunded.
- Leases last at most 60 seconds; progress renews within the task deadline. At most three claims per assignment. Expired leases may be reclaimed within budget; stale leases cannot report. Task deadlines range from 30–3600 seconds, default 600.
- Children require the same origin, depth at most two, and share root budget/deadline. Correlation is not a DAG: parent status aggregates its own assignments, not every descendant.
- Origin and room owner see the whole task. Workers see their own instruction/result plus shared context. Unrelated members and other rooms are denied. Removing/rejoining creates a new membership epoch and does not restore old task access.
- At most 100 context additions. Around 60 events per handoff stops further progress updates, but final results remain allowed. Up to three inert text artifacts, 80-character names and 2000-character bodies; no execution or URL fetching.
- New tasks and leases survive restart; no external work runs automatically. Workers inspect state and renew or reclaim. Old discussion mode still marks pending work interrupted on restart.
- Identical actor/epoch/operation/request_id and arguments replay the original response; conflicting arguments return 409. Claim replay does not renew a lease and may return an expired one. Credentials are hashed, but **claim idempotency receipts contain temporary lease plaintext**: protect the database and backups as sensitive data. Logs and ordinary task snapshots do not expose leases.
- Single-process SQLite transactions serialize claim/report/cancel. External exactly-once execution and cancellation are not guaranteed. Task text/results are unencrypted; production quotas and account infrastructure are not provided. Share only explicitly authorized task context, never an entire personal native conversation.

## Shared HTTP model

Owner base: `/api/rooms/{room}/tasks`. Agent base: `/api/rooms/{room}/agents/{agent}/peer/tasks`. Use the corresponding Bearer credential. GET lists, POST to base creates; POST `/query`, `/inbox`, `/claim`, `/update`, `/context`, `/retry`, `/cancel` map to tools. Web and MCP share the same store and event cursor. Payloads cannot replace authenticated identity or expand room scope.

## dot hosted plugin authentication gate / dot 托管插件认证门槛

[Official authentication guidance](https://developers.openai.com/plugins/build/auth) requires OAuth 2.1 for authenticated hosted MCP plugins; an OAuth access token is not an arbitrary custom static API key. The current static-Bearer gateway does not implement this flow. Follow the [official connection steps](https://developers.openai.com/plugins/deploy/connect-chatgpt) only after compatible HTTPS/OAuth infrastructure exists, install the plugin, then verify actual tool visibility in the owner's active dot task. This remains unverified and blocked on that infrastructure; no fake OAuth compatibility is claimed. Grok desktop also executes on its cloud computer, so a desktop UI does not make the user's localhost reachable.

认证 hosted MCP plugin 预期 OAuth 2.1，不能直接把当前静态 token 当作自定义 API key 填入后宣称可用。需先准备兼容 HTTPS/OAuth 接入，再按官方步骤添加/安装 plugin，并在 owner 主动发起的 dot 任务中验证工具可见性。本项目尚未实现或验证这条产品接线路径；Grok 桌面端的云电脑同样不能直接访问用户电脑的 localhost。
