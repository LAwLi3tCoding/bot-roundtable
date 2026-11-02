"""Synthetic Dot contract tests; no vendor accounts or automatic wake claims."""

import hashlib
import json
import re
import secrets
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from local_client import LocalClient, LocalFailure, save_evidence
from roundtable import Store
from server import make_server


class RoundtripTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("Roundtrip")["id"]
        origin = self.store.add_agent(self.room, "origin")
        worker = self.store.add_agent(self.room, "dot")
        self.store.grant(self.room, "origin", 4)
        self.server = make_server(self.store, secrets.token_urlsafe(32), port=0)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.start()
        base = f"http://127.0.0.1:{self.server.server_port}"
        self.origin = LocalClient(base, self.room, "origin", origin["token"])
        self.worker = LocalClient(base, self.room, "dot", worker["token"])
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "evidence.json"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join()
        self.store.db.close()
        self.tmp.cleanup()

    def test_synthetic_worker_roundtrip_and_scoped_doctor_evidence(self):
        errors = []

        def worker():
            try:
                for _ in range(100):
                    jobs = self.worker.call("inbox", {})
                    if jobs:
                        break
                    time.sleep(0.02)
                job = jobs[0]
                claim = self.worker.call(
                    "claim",
                    dict(
                        task_id=job["task_id"],
                        assignment_id=job["id"],
                        expected_attempt=job["attempt"],
                        request_id="claim",
                    ),
                )
                nonce = re.search(r"roundtrip:[a-f0-9]{32}", job["instruction"]).group()
                self.worker.call(
                    "report",
                    dict(
                        task_id=job["task_id"],
                        assignment_id=job["id"],
                        attempt=claim["attempt"],
                        lease=claim["lease"],
                        kind="completed",
                        body=nonce,
                        request_id="report",
                    ),
                )
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        result = self.origin.roundtrip("dot", self.path, timeout=30, test=True)
        thread.join(5)
        self.assertFalse(errors)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["correlated"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        report = self.origin.evidence(self.path)
        self.assertTrue(report["protocol_roundtrip_verified"]["verified"])
        self.assertFalse(report["native_roundtrip_verified"]["verified"])
        self.assertFalse(report["wake_verified"]["verified"])
        self.assertFalse(self.worker.evidence(self.path)["protocol_roundtrip_verified"]["verified"])
        result["operator_observations"] = {
            "native_roundtrip": dict(
                confirmed=True,
                source="operator",
                task_id=result["task_id"],
                assignment_id=result["assignment_id"],
                observed_at=time.time(),
            )
        }
        save_evidence(self.path, result)
        self.assertFalse(self.origin.evidence(self.path)["native_roundtrip_verified"]["verified"])
        result["test"] = False
        save_evidence(self.path, result)
        self.assertTrue(self.origin.evidence(self.path)["native_roundtrip_verified"]["verified"])
        self.assertFalse(self.origin.evidence(self.path)["wake_verified"]["verified"])
        result["expected_result_digest"] = hashlib.sha256(b"wrong").hexdigest()
        save_evidence(self.path, result)
        self.assertFalse(self.origin.evidence(self.path)["protocol_roundtrip_verified"]["verified"])

    def test_wait_timeout_persists_unknown_without_cancelling_or_faking_success(self):
        with patch.object(self.origin, "wait", side_effect=LocalFailure("wait_timeout")):
            with self.assertRaisesRegex(LocalFailure, "wait_timeout"):
                self.origin.roundtrip("dot", self.path, timeout=30, test=True)
        result = json.loads(self.path.read_text())
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["correlated"])
        self.assertEqual(
            self.origin.call("task", {"task_id": result["task_id"]})["task"]["status"], "running"
        )
        self.assertFalse(self.origin.evidence(self.path)["protocol_roundtrip_verified"]["verified"])

    def test_roundtrip_timeout_reaches_task_and_wait_unchanged(self):
        for seconds in (30, 86400):
            with patch.object(
                self.origin, "wait", side_effect=LocalFailure("wait_timeout")
            ) as wait:
                with self.assertRaises(LocalFailure):
                    self.origin.roundtrip("dot", self.path, timeout=seconds, test=True)
                evidence = json.loads(self.path.read_text())
                wait.assert_called_once_with(evidence["task_id"], seconds)
            task = self.origin.call("task", {"task_id": evidence["task_id"]})["task"]
            self.assertAlmostEqual(task["deadline"] - task["created"], seconds, places=3)

    def test_doctor_reports_safe_outbound_and_worker_status(self):
        with patch.dict(
            "os.environ", {"HTTPS_PROXY": "http://synthetic-private-proxy:9999"}, clear=True
        ):
            report = self.origin.call("doctor")
        self.assertEqual(report["outbound_local"]["reason"], "explicit_outbound_proxy_required")
        self.assertEqual(report["outbound_backend"]["reason"], "explicit_outbound_proxy_required")
        self.assertEqual(report["terminal_worker"]["state"], "disabled")
        self.assertNotIn("synthetic-private-proxy", json.dumps(report))

    def test_invalid_wait_options_do_not_create_tasks(self):
        for value in (0, -1, 29, 30.5, float("nan"), float("inf"), 86401):
            with self.assertRaises(ValueError):
                self.origin.roundtrip("dot", self.path, timeout=value)
        with self.assertRaises(ValueError):
            self.origin.roundtrip("origin", self.path)
        self.assertEqual(self.origin.call("tasks"), [])
        self.assertFalse(self.path.exists())

    def test_http_mcp_events_simulated_dot_worker_roundtrip(self):
        import asyncio
        import socket
        from contextlib import AsyncExitStack
        import httpx
        import uvicorn
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from mcp_http import build_http_app
        from test_mcp_events import Receiver, subscription
        from test_mcp_http import unpack

        receiver = Receiver()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        grants = json.dumps(
            [dict(room=self.room, agent=c.agent, token=c.token) for c in (self.origin, self.worker)]
        )
        app = build_http_app(
            f"http://127.0.0.1:{self.server.server_port}",
            grants,
            port,
            events_db=str(Path(self.tmp.name) / "events.db"),
            event_transport=receiver,
        )
        http_server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
        thread = threading.Thread(target=http_server.run, kwargs={"sockets": [sock]})
        thread.start()
        for _ in range(500):
            if http_server.started:
                break
            time.sleep(0.01)
        self.assertTrue(http_server.started)

        async def exercise():
            url = f"http://127.0.0.1:{port}/mcp"
            async with AsyncExitStack() as stack:
                http = await stack.enter_async_context(
                    httpx.AsyncClient(
                        trust_env=False, headers={"Authorization": "Bearer " + self.worker.token}
                    )
                )
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(url, http_client=http)
                )
                session = await stack.enter_async_context(ClientSession(read, write))
                init = await session.initialize()
                self.assertIn("events", init.capabilities.model_dump())
                response = await http.post(
                    url,
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": "2025-03-26",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "events/subscribe",
                        "params": subscription(),
                    },
                )
                self.assertIn("id", response.json()["result"])
                roundtrip = asyncio.create_task(
                    asyncio.to_thread(self.origin.roundtrip, "dot", self.path, 30, True)
                )
                for _ in range(500):
                    if any(r[0].get("name") == "roundtable.notification" for r in receiver.records):
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(
                    any(r[0].get("name") == "roundtable.notification" for r in receiver.records)
                )
                jobs = unpack(await session.call_tool("receive_assignments"))
                job = jobs[0]
                claim = unpack(
                    await session.call_tool(
                        "claim_assignment",
                        dict(
                            task_id=job["task_id"],
                            assignment_id=job["id"],
                            expected_attempt=job["attempt"],
                            request_id="http-claim",
                        ),
                    )
                )
                common = dict(
                    task_id=job["task_id"],
                    assignment_id=job["id"],
                    lease=claim["lease"],
                    attempt=claim["attempt"],
                )
                await session.call_tool(
                    "report_assignment",
                    dict(
                        **common,
                        kind="progress",
                        body="Synthetic worker received approved read-only probe",
                        request_id="http-progress",
                    ),
                )
                nonce = re.search(r"roundtrip:[a-f0-9]{32}", job["instruction"]).group()
                result = unpack(
                    await session.call_tool(
                        "report_assignment",
                        dict(**common, kind="completed", body=nonce, request_id="http-completed"),
                    )
                )
                self.assertEqual(result["status"], "completed")
                evidence = await roundtrip
                self.assertTrue(evidence["correlated"])
                self.assertFalse(self.origin.evidence(self.path)["wake_verified"]["verified"])

        try:
            asyncio.run(exercise())
        finally:
            http_server.should_exit = True
            thread.join(10)
            self.assertFalse(thread.is_alive())


class WaitDeadlineTests(unittest.TestCase):
    def test_trickling_response_cannot_extend_total_wait(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        stopped = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(200)
                self.send_header("Content-Length", "10000")
                self.end_headers()
                try:
                    for _ in range(1000):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        if stopped.wait(0.01):
                            break
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        client = LocalClient(f"http://127.0.0.1:{server.server_port}", "a" * 24, "origin", "a" * 32)
        start = time.monotonic()
        try:
            with self.assertRaisesRegex(LocalFailure, "wait_timeout"):
                client.wait("b" * 24, timeout=0.15)
            self.assertLess(time.monotonic() - start, 0.6)
        finally:
            stopped.set()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_stalled_resolution_workers_are_bounded(self):
        import local_client
        from unittest.mock import patch

        release = threading.Event()
        calls = []
        client = LocalClient("http://localhost:8765", "a" * 24, "origin", "a" * 32)

        def stalled(*args, **kwargs):
            calls.append(True)
            release.wait(3)
            raise LocalFailure("backend_unreachable")

        semaphore = threading.BoundedSemaphore(2)
        with (
            patch.object(local_client, "_WAIT_SLOTS", semaphore),
            patch.object(client, "call", side_effect=stalled),
        ):
            try:
                for _ in range(2):
                    with self.assertRaisesRegex(LocalFailure, "wait_timeout"):
                        client.wait("b" * 24, timeout=0.03)
                with self.assertRaisesRegex(LocalFailure, "wait_capacity_exhausted"):
                    client.wait("b" * 24, timeout=0.03)
                self.assertEqual(len(calls), 2)
            finally:
                release.set()
                # Wait for both slots to return before restoring module semaphore.
                self.assertTrue(semaphore.acquire(timeout=2))
                self.assertTrue(semaphore.acquire(timeout=2))
                semaphore.release()
                semaphore.release()
