"""Actual JSON-RPC MCP client over stdio; no model/provider calls."""

import asyncio
from contextlib import AsyncExitStack
import json
import os
import secrets
import sys
import threading
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from roundtable import Store
from server import make_server

ROOT = Path(__file__).resolve().parents[1]


def unpack(result):
    if result.isError:
        raise AssertionError(result.content)
    if result.structuredContent is not None:
        return result.structuredContent.get("result", result.structuredContent)
    return json.loads(result.content[0].text)


class MCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_client_initialize_tools_send_poll_stop(self):
        store = Store(demo=True)
        room = store.room("MCP spike")
        store.settings(room["id"], "MCP spike", "demo-planner")
        server = make_server(store, secrets.token_urlsafe(32), port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "mcp_bridge.py")],
            env={
                **os.environ,
                "ROUNDTABLE_URL": f"http://127.0.0.1:{server.server_port}",
                "ROUNDTABLE_ROOM": room["id"],
                "ROUNDTABLE_TOKEN": room["token"],
                "ROUNDTABLE_AGENT": "",
            },
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    self.assertTrue(init.protocolVersion)
                    names = {t.name for t in (await session.list_tools()).tools}
                    self.assertTrue(
                        {"list_rooms", "list_bots", "send_message", "get_thread", "stop_discussion"}
                        <= names
                    )
                    listed = await session.call_tool("list_rooms")
                    self.assertFalse(listed.isError)
                    bots = await session.call_tool("list_bots")
                    self.assertFalse(bots.isError)
                    result = unpack(
                        await session.call_tool(
                            "send_message",
                            {
                                "body": "MCP synthetic topic",
                                "targets": ["demo-planner", "demo-critic"],
                                "budget": 4,
                                "request_id": "spike-1",
                            },
                        )
                    )
                    self.assertEqual(result["status"], "running")
                    for _ in range(4):
                        store.demo_tick()
                        await asyncio.sleep(0.01)
                    state = unpack(await session.call_tool("get_thread", {"run_id": result["id"]}))
                    self.assertEqual(state["runs"][0]["status"], "completed")
                    self.assertEqual(len(state["messages"]), 5)
                    self.assertEqual(
                        {m["sender"] for m in state["messages"][1:]},
                        {"demo-planner", "demo-critic"},
                    )
                    store.settings(room["id"], "MCP spike", "")
                    second = unpack(
                        await session.call_tool(
                            "send_message",
                            {
                                "body": "Stop me",
                                "targets": ["demo-planner"],
                                "budget": 20,
                                "request_id": "spike-2",
                            },
                        )
                    )
                    unpack(await session.call_tool("stop_discussion"))
                    state = unpack(await session.call_tool("get_thread", {"run_id": second["id"]}))
                    self.assertEqual(state["runs"][0]["status"], "stopped")
                    self.assertEqual(len(state["messages"]), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.db.close()

    async def test_agent_receivers_identity_allowance_replay_and_revocation(self):
        store = Store(demo=True)
        room = store.room("Agent MCP")
        other = store.room("Private other room")
        caller = store.add_agent(room["id"], "initiator")
        lead = store.add_agent(room["id"], "existing-lead")
        receiver = store.add_agent(room["id"], "existing-peer")
        store.grant(room["id"], "initiator", 3)
        store.settings(room["id"], "Agent MCP", "existing-lead")
        server = make_server(store, secrets.token_urlsafe(32), port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            async with AsyncExitStack() as stack:
                sessions = {}
                for credential in (caller, lead, receiver):
                    params = StdioServerParameters(
                        command=sys.executable,
                        args=[str(ROOT / "mcp_bridge.py")],
                        env={
                            **os.environ,
                            "ROUNDTABLE_URL": f"http://127.0.0.1:{server.server_port}",
                            "ROUNDTABLE_ROOM": room["id"],
                            "ROUNDTABLE_TOKEN": credential["token"],
                            "ROUNDTABLE_AGENT": credential["id"],
                        },
                    )
                    read, write = await stack.enter_async_context(stdio_client(params))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    sessions[credential["id"]] = session
                initiator = sessions["initiator"]
                self.assertEqual(
                    [r["id"] for r in unpack(await initiator.call_tool("list_rooms"))], [room["id"]]
                )
                own = await initiator.call_tool(
                    "send_message",
                    {"body": "self", "targets": ["initiator"], "budget": 3, "request_id": "self"},
                )
                self.assertTrue(own.isError)
                result = unpack(
                    await initiator.call_tool(
                        "send_message",
                        {
                            "body": "synthetic existing bots",
                            "targets": ["existing-peer"],
                            "budget": 3,
                            "request_id": "agents-1",
                        },
                    )
                )
                for aid, phase in (
                    ("existing-lead", "lead-plan"),
                    ("existing-peer", "contribute"),
                    ("existing-lead", "lead-summary"),
                ):
                    session = sessions[aid]
                    jobs = unpack(await session.call_tool("receive_jobs"))
                    self.assertEqual(len(jobs), 1)
                    job = jobs[0]
                    self.assertEqual(job["phase"], phase)
                    self.assertEqual(job["run"], result["id"])
                    if phase == "lead-plan":
                        wrong = await sessions["existing-peer"].call_tool(
                            "reply_to_job", {"job_id": job["id"], "body": "spoof"}
                        )
                        self.assertTrue(wrong.isError)
                    reply = {"job_id": job["id"], "body": "Synthetic reply for " + phase}
                    self.assertFalse(
                        unpack(await session.call_tool("reply_to_job", reply))["duplicate"]
                    )
                    self.assertTrue(
                        unpack(await session.call_tool("reply_to_job", reply))["duplicate"]
                    )
                state = unpack(await initiator.call_tool("get_thread", {"run_id": result["id"]}))
                self.assertEqual(state["runs"][0]["status"], "completed")
                self.assertEqual(state["messages"][0]["sender"], "bot:initiator")
                self.assertEqual(len(state["messages"]), 4)
                self.assertNotIn(other["id"], json.dumps(state))
                exhausted = await initiator.call_tool(
                    "send_message",
                    {
                        "body": "again",
                        "targets": ["existing-peer"],
                        "budget": 3,
                        "request_id": "agents-2",
                    },
                )
                self.assertTrue(exhausted.isError)
                store.remove_agent(room["id"], "existing-peer")
                store.add_agent(room["id"], "existing-peer")
                self.assertTrue((await sessions["existing-peer"].call_tool("list_bots")).isError)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.db.close()
