"""Real MCP SDK Streamable HTTP clients against a loopback uvicorn server."""

import asyncio
import json
import http.client
import io
import logging
import secrets
import socket
import threading
import unittest
from contextlib import AsyncExitStack
from unittest.mock import patch

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mcp_http import ScopedVerifier, build_http_app, parse_grants
from roundtable import Store
from server import make_server


def unpack(result):
    if result.isError:
        raise AssertionError(result.content)
    if result.structuredContent is not None:
        return result.structuredContent.get("result", result.structuredContent)
    return json.loads(result.content[0].text)


class HTTPMCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store()
        self.room = self.store.room("HTTP room")
        self.other = self.store.room("Private HTTP room")
        self.caller = self.store.add_agent(self.room["id"], "http-caller")
        self.receiver = self.store.add_agent(self.room["id"], "http-receiver")
        self.second = self.store.add_agent(self.room["id"], "http-second")
        self.foreign = self.store.add_agent(self.other["id"], "http-foreign")
        self.store.grant(self.room["id"], "http-caller", 4)
        self.backend = make_server(self.store, secrets.token_urlsafe(32), port=0)
        self.backend_thread = threading.Thread(target=self.backend.serve_forever)
        self.backend_thread.start()
        grants = [
            {"room": self.room["id"], "agent": c["id"], "token": c["token"]}
            for c in (self.caller, self.receiver, self.second)
        ] + [
            {"room": self.other["id"], "agent": self.foreign["id"], "token": self.foreign["token"]}
        ]
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        app = build_http_app(
            f"http://127.0.0.1:{self.backend.server_port}",
            json.dumps(grants),
            self.port,
            public_url="https://bots.example.com/mcp",
        )
        self.http_server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=self.port,
                log_level="critical",
                access_log=False,
                proxy_headers=False,
            )
        )
        self.http_thread = threading.Thread(
            target=self.http_server.run, kwargs={"sockets": [self.socket]}
        )
        self.http_thread.start()
        for _ in range(500):
            if self.http_server.started:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(self.http_server.started)

    async def asyncTearDown(self):
        self.http_server.should_exit = True
        await asyncio.to_thread(self.http_thread.join, 5)
        self.assertFalse(self.http_thread.is_alive())
        await asyncio.to_thread(self.backend.shutdown)
        self.backend.server_close()
        self.backend_thread.join()
        self.store.db.close()

    async def connect(self, stack, credential):
        client = await stack.enter_async_context(
            httpx.AsyncClient(
                headers={"Authorization": "Bearer " + credential["token"]},
                trust_env=False,
                timeout=10,
            )
        )
        read, write, _ = await stack.enter_async_context(
            streamable_http_client(self.url, http_client=client)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        initialized = await session.initialize()
        self.assertTrue(initialized.protocolVersion)
        return session

    async def test_real_http_protocol_scoped_clients_send_receive_poll_stop(self):
        async with AsyncExitStack() as stack:
            caller = await self.connect(stack, self.caller)
            receiver = await self.connect(stack, self.receiver)
            foreign = await self.connect(stack, self.foreign)
            tools = {tool.name for tool in (await caller.list_tools()).tools}
            self.assertEqual(len(tools), 16)
            # Interleave different authenticated principals; no session or context leakage.
            listed = await asyncio.gather(
                caller.call_tool("list_rooms"), foreign.call_tool("list_rooms")
            )
            self.assertEqual(unpack(listed[0])[0]["id"], self.room["id"])
            self.assertEqual(unpack(listed[1])[0]["id"], self.other["id"])
            run = unpack(
                await caller.call_tool(
                    "send_message",
                    {
                        "body": "HTTP synthetic topic",
                        "targets": ["http-receiver"],
                        "budget": 1,
                        "request_id": "http-1",
                    },
                )
            )
            job = unpack(await receiver.call_tool("receive_jobs"))[0]
            self.assertEqual(job["run"], run["id"])
            self.assertEqual(
                unpack(await foreign.call_tool("get_thread", {"run_id": run["id"]}))["messages"], []
            )
            self.assertTrue(
                (
                    await foreign.call_tool("reply_to_job", {"job_id": job["id"], "body": "spoof"})
                ).isError
            )
            self.assertFalse(
                unpack(
                    await receiver.call_tool(
                        "reply_to_job", {"job_id": job["id"], "body": "HTTP reply"}
                    )
                )["duplicate"]
            )
            result = unpack(await caller.call_tool("get_thread", {"run_id": run["id"]}))
            self.assertEqual(result["runs"][0]["status"], "completed")
            self.assertEqual(
                [m["sender"] for m in result["messages"]], ["bot:http-caller", "http-receiver"]
            )
            next_run = unpack(
                await caller.call_tool(
                    "send_message",
                    {
                        "body": "stop",
                        "targets": ["http-receiver"],
                        "budget": 2,
                        "request_id": "http-2",
                    },
                )
            )
            self.assertTrue((await receiver.call_tool("stop_discussion")).isError)
            unpack(await caller.call_tool("stop_discussion"))
            self.assertEqual(
                unpack(await caller.call_tool("get_thread", {"run_id": next_run["id"]}))["runs"][0][
                    "status"
                ],
                "stopped",
            )

    async def test_native_task_two_workers_fanin_web_events_and_cancel(self):
        self.store.settings(self.room["id"], "HTTP room", self.caller["id"])
        async with AsyncExitStack() as stack:
            origin = await self.connect(stack, self.caller)
            one = await self.connect(stack, self.receiver)
            two = await self.connect(stack, self.second)
            outsider = await self.connect(stack, self.foreign)
            payload = dict(
                title="Native task",
                context="Explicit scoped context",
                assignments=[
                    dict(worker=self.receiver["id"], instruction="Research independently"),
                    dict(worker=self.second["id"], instruction="Review independently"),
                ],
                request_id="native-task",
                budget=4,
            )
            task = unpack(await origin.call_tool("create_task", payload))
            self.assertEqual(task, unpack(await origin.call_tool("create_task", payload)))
            self.assertTrue(
                (await origin.call_tool("create_task", {**payload, "context": "conflict"})).isError
            )
            tid = task["task_id"]
            self.assertEqual(task["origin"], "bot:" + self.caller["id"])
            self.assertTrue((await outsider.call_tool("get_task", {"task_id": tid})).isError)
            inbox_one = unpack(await one.call_tool("receive_assignments"))
            inbox_two = unpack(await two.call_tool("receive_assignments"))
            self.assertEqual(len(inbox_one), 1)
            self.assertEqual(len(inbox_two), 1)
            self.assertNotEqual(inbox_one[0]["id"], inbox_two[0]["id"])
            claims = []
            for client, job in ((one, inbox_one[0]), (two, inbox_two[0])):
                claims.append(
                    unpack(
                        await client.call_tool(
                            "claim_assignment",
                            dict(
                                task_id=tid,
                                assignment_id=job["id"],
                                expected_attempt=0,
                                request_id="claim",
                            ),
                        )
                    )
                )
            report = dict(
                task_id=tid,
                assignment_id=claims[0]["assignment_id"],
                lease=claims[0]["lease"],
                attempt=1,
                kind="progress",
                body="Research progress",
                request_id="progress",
            )
            self.assertTrue((await two.call_tool("report_assignment", report)).isError)
            unpack(await one.call_tool("report_assignment", report))
            unpack(
                await origin.call_tool(
                    "add_task_context", dict(task_id=tid, body="Owner follow-up", request_id="note")
                )
            )
            async with httpx.AsyncClient(trust_env=False) as web:
                url = f"http://127.0.0.1:{self.backend.server_port}/api/rooms/{self.room['id']}"
                headers = {"Authorization": "Bearer " + self.room["token"]}
                state = (await web.get(url, headers=headers)).json()
                self.assertEqual(state["tasks"][0]["task"]["id"], tid)
                web_task = (
                    await web.post(url + "/tasks/query", headers=headers, json={"task_id": tid})
                ).json()
                native = unpack(await origin.call_tool("get_task", {"task_id": tid}))
                self.assertEqual(web_task["events"], native["events"])
                self.assertIn("Research progress", str(web_task))
                cursor = native["cursor"]
            unpack(
                await one.call_tool(
                    "report_assignment",
                    {
                        **report,
                        "kind": "completed",
                        "body": "Research result",
                        "request_id": "done",
                        "artifacts": [{"name": "Notes", "text": "Inert result text"}],
                    },
                )
            )
            failed = dict(
                task_id=tid,
                assignment_id=claims[1]["assignment_id"],
                lease=claims[1]["lease"],
                attempt=1,
                kind="failed",
                body="Synthetic failure",
                request_id="failed",
            )
            unpack(await two.call_tool("report_assignment", failed))
            unpack(
                await origin.call_tool(
                    "retry_assignment",
                    dict(task_id=tid, assignment_id=claims[1]["assignment_id"], request_id="retry"),
                )
            )
            retry = unpack(
                await two.call_tool(
                    "claim_assignment",
                    dict(
                        task_id=tid,
                        assignment_id=claims[1]["assignment_id"],
                        expected_attempt=1,
                        request_id="claim2",
                    ),
                )
            )
            unpack(
                await two.call_tool(
                    "report_assignment",
                    {
                        **failed,
                        "lease": retry["lease"],
                        "attempt": 2,
                        "kind": "completed",
                        "body": "Review result",
                        "request_id": "done",
                    },
                )
            )
            final = unpack(await origin.call_tool("get_task", dict(task_id=tid, after=cursor)))
            self.assertEqual(final["task"]["status"], "completed")
            self.assertEqual(
                {a["result"] for a in final["assignments"]}, {"Research result", "Review result"}
            )
            self.assertTrue(all(e["id"] > cursor for e in final["events"]))
            cancelled = unpack(
                await origin.call_tool(
                    "create_task",
                    {
                        **payload,
                        "assignments": payload["assignments"][:1],
                        "request_id": "cancelled",
                    },
                )
            )
            job = unpack(await one.call_tool("receive_assignments"))[0]
            claim = unpack(
                await one.call_tool(
                    "claim_assignment",
                    dict(
                        task_id=cancelled["task_id"],
                        assignment_id=job["id"],
                        expected_attempt=0,
                        request_id="claim-cancel",
                    ),
                )
            )
            self.assertTrue(
                (
                    await one.call_tool(
                        "cancel_task", dict(task_id=cancelled["task_id"], request_id="forbidden")
                    )
                ).isError
            )
            unpack(
                await origin.call_tool(
                    "cancel_task", dict(task_id=cancelled["task_id"], request_id="cancel")
                )
            )
            self.assertTrue(
                (
                    await one.call_tool(
                        "report_assignment",
                        dict(
                            task_id=cancelled["task_id"],
                            assignment_id=job["id"],
                            lease=claim["lease"],
                            attempt=1,
                            kind="completed",
                            body="Late",
                            request_id="late",
                        ),
                    )
                ).isError
            )

    async def test_unauthorized_origin_host_revocation_and_no_cors(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "security-test", "version": "1"},
            },
        }
        common = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            for token in ("", "invalid", self.room["token"]):
                response = await client.post(
                    self.url,
                    json=payload,
                    headers={**common, **({"Authorization": "Bearer " + token} if token else {})},
                )
                self.assertEqual(response.status_code, 401)
                self.assertIn("Bearer", response.headers["www-authenticate"])
            authorized = {**common, "Authorization": "Bearer " + self.receiver["token"]}
            for headers in (
                {"Origin": "https://evil.example"},
                {"Host": "evil.example"},
                {"Origin": "null"},
                {"Host": "bots.example.com.evil"},
            ):
                response = await client.post(
                    self.url, json=payload, headers={**authorized, **headers}
                )
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("access-control-allow-origin", response.headers)
            # Explicit configured HTTPS proxy host/origin is allowed, never arbitrary forwarded headers.
            good = await client.post(
                self.url,
                json=payload,
                headers={
                    **authorized,
                    "Host": "bots.example.com",
                    "Origin": "https://bots.example.com",
                },
            )
            self.assertEqual(good.status_code, 200)
            self.store.remove_agent(self.room["id"], "http-receiver")
            self.store.add_agent(self.room["id"], "http-receiver")
            revoked = await client.post(self.url, json=payload, headers=authorized)
            self.assertEqual(revoked.status_code, 401)

    async def test_slow_backend_does_not_block_another_principals_tools(self):
        entered = threading.Event()
        release = threading.Event()
        real_connection = http.client.HTTPConnection
        caller_token = self.caller["token"]

        class DelayedConnection:
            def __init__(self, *args, **kwargs):
                self.connection = real_connection(*args, **kwargs)
                self.delayed = False

            def request(self, method, path, body=None, headers=None):
                self.delayed = (
                    path.endswith("/peer")
                    and (headers or {}).get("Authorization") == "Bearer " + caller_token
                )
                return self.connection.request(method, path, body, headers or {})

            def getresponse(self):
                if self.delayed:
                    entered.set()
                    release.wait(3)
                return self.connection.getresponse()

            def close(self):
                self.connection.close()

        async with AsyncExitStack() as stack:
            caller = await self.connect(stack, self.caller)
            foreign = await self.connect(stack, self.foreign)
            with patch("mcp_bridge.http.client.HTTPConnection", DelayedConnection):
                slow = asyncio.create_task(caller.call_tool("list_rooms"))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    fast = await asyncio.wait_for(foreign.call_tool("list_rooms"), timeout=1)
                    self.assertEqual(unpack(fast)[0]["id"], self.other["id"])
                finally:
                    release.set()
                    slow_result = await slow
                self.assertEqual(unpack(slow_result)[0]["id"], self.room["id"])

    async def test_backend_rechecks_revoked_grant_after_gateway_verification(self):
        original = ScopedVerifier.still_authorized
        revoked = False

        def revoke_after_check(verifier, grant):
            nonlocal revoked
            authorized = original(verifier, grant)
            if authorized and not revoked and grant.agent == self.receiver["id"]:
                revoked = True
                self.store.remove_agent(self.room["id"], self.receiver["id"])
                self.store.add_agent(self.room["id"], self.receiver["id"])
            return authorized

        async with AsyncExitStack() as stack:
            receiver = await self.connect(stack, self.receiver)
            # Complete initialized notification traffic before injecting the race.
            await receiver.list_tools()
            with patch.object(ScopedVerifier, "still_authorized", revoke_after_check):
                result = await receiver.call_tool("get_thread")
            self.assertTrue(revoked)
            self.assertTrue(result.isError)
            self.assertNotIn(self.room["name"], str(result.content))

    async def test_ambiguous_headers_and_sensitive_data_not_logged(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        root = logging.getLogger()
        root.addHandler(handler)
        secret_body = "synthetic-private-body-871ad0"
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                response = await client.post(
                    self.url,
                    content=b"{}",
                    headers=[
                        ("Authorization", "Bearer " + self.caller["token"]),
                        ("Authorization", "Bearer " + self.foreign["token"]),
                    ],
                )
                self.assertEqual(response.status_code, 403)
            async with AsyncExitStack() as stack:
                caller = await self.connect(stack, self.caller)
                result = await caller.call_tool(
                    "send_message",
                    {
                        "body": secret_body,
                        "targets": ["http-receiver"],
                        "budget": 1,
                        "request_id": "logs",
                    },
                )
                self.assertFalse(result.isError)
                await caller.call_tool("stop_discussion")
        finally:
            root.removeHandler(handler)
        logs = output.getvalue()
        self.assertNotIn(secret_body, logs)
        for credential in (self.caller, self.foreign, self.receiver):
            self.assertNotIn(credential["token"], logs)

    def test_grants_reject_ambiguous_or_owner_credentials(self):
        grant = {"room": self.room["id"], "agent": "http-caller", "token": self.caller["token"]}
        for value in (
            [],
            [grant, grant],
            [{**grant, "agent": "user"}],
            [{**grant, "room": "../other"}],
            [{**grant, "token": "short"}],
        ):
            with self.assertRaises(ValueError):
                parse_grants(json.dumps(value))
