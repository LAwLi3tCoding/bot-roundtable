import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import socket
import tempfile
import threading
import time
import unittest
from contextlib import AsyncExitStack
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from event_delivery import CallbackTransport, encode, signed_headers
from mcp_events import EventBroker, EventError
from mcp_http import ScopedVerifier, build_http_app, parse_grants
from roundtable import Store
from server import make_server

SECRET = "whsec_" + base64.b64encode(b"synthetic-contract-key-32-bytes!!!").decode()


class Receiver(CallbackTransport):
    """Injected test receiver only; no sockets, production URL policy unchanged."""

    def __init__(self):
        super().__init__(["callback.example.com"])
        self.records = []
        self.status = 200
        self.challenge_ok = True

    def post(self, url, body, headers):
        self.validate(url)
        data = json.loads(body)
        self.records.append((data, headers, body))
        if data.get("type") == "verification":
            return 200, encode({"challenge": data["challenge"] if self.challenge_ok else "wrong"})
        return self.status, b"{}"


def subscription(name="handoff.available", arguments=None, secret=SECRET):
    return {
        "name": name,
        "arguments": arguments or {},
        "delivery": {
            "mode": "webhook",
            "url": "https://callback.example.com/unique",
            "secret": secret,
        },
    }


class EventsFixture(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("Event contracts")
        self.origin = self.store.add_agent(self.room["id"], "event-origin")
        self.worker = self.store.add_agent(self.room["id"], "event-worker")
        self.store.grant(self.room["id"], self.origin["id"], 20)
        self.server = make_server(self.store, secrets.token_urlsafe(32), port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.grants = json.dumps(
            [
                dict(room=self.room["id"], agent=a["id"], token=a["token"])
                for a in (self.origin, self.worker)
            ]
        )
        self.verifier = ScopedVerifier(self.base, parse_grants(self.grants))
        self.current = self.worker
        self.verifier.identity = lambda: (
            self.room["id"],
            self.current["token"],
            self.current["id"],
        )
        self.receiver = Receiver()
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "events.db")
        self.broker = EventBroker(self.path, self.verifier, self.receiver)

    def tearDown(self):
        self.broker.db.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.db.close()
        self.temp.cleanup()

    def create(self, nonce="task"):
        return self.store.handoffs.create(
            self.room["id"],
            "bot:event-origin",
            {
                "title": "Synthetic task",
                "context": "PRIVATE CONTEXT NOT IN EVENT",
                "request_id": nonce,
                "assignments": [{"worker": "event-worker", "instruction": "PRIVATE INSTRUCTION"}],
            },
        )

    def test_verify_idempotency_signed_delivery_and_unsubscribe(self):
        params = subscription()
        first = self.broker.rpc("events/subscribe", params)
        second = self.broker.rpc("events/subscribe", params)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.receiver.records), 1)
        self.create()
        self.broker.dispatch_once()
        event, headers, body = self.receiver.records[-1]
        self.assertEqual(event["name"], "handoff.available")
        self.assertNotIn(b"PRIVATE", body)
        self.assertEqual(headers["webhook-id"], event["eventId"])
        signed = (headers["webhook-id"] + "." + headers["webhook-timestamp"] + ".").encode() + body
        expected = (
            "v1,"
            + base64.b64encode(
                hmac.new(base64.b64decode(SECRET[6:]), signed, hashlib.sha256).digest()
            ).decode()
        )
        self.assertEqual(headers["webhook-signature"], expected)
        self.assertNotEqual(
            expected,
            signed_headers(
                SECRET,
                first["id"],
                event["eventId"],
                body + b" ",
                now=int(headers["webhook-timestamp"]),
            )["webhook-signature"],
        )
        del params["delivery"]["secret"]
        self.broker.rpc("events/unsubscribe", params)
        self.broker.rpc("events/unsubscribe", params)
        count = len(self.receiver.records)
        self.create("later")
        self.broker.dispatch_once()
        self.assertEqual(len(self.receiver.records), count)

    def test_verification_cache_does_not_slide_and_retries_are_bounded(self):
        params = subscription()
        sid = self.broker.rpc("events/subscribe", params)["id"]
        before = self.broker.db.execute(
            "SELECT verified FROM subscriptions WHERE id=?", (sid,)
        ).fetchone()[0]
        self.broker.rpc("events/subscribe", params)
        self.assertEqual(
            self.broker.db.execute(
                "SELECT verified FROM subscriptions WHERE id=?", (sid,)
            ).fetchone()[0],
            before,
        )
        self.broker.db.execute("UPDATE subscriptions SET verified=0")
        self.broker.db.commit()
        self.broker.rpc("events/subscribe", params)
        self.assertEqual(len(self.receiver.records), 2)
        self.create()
        self.receiver.status = 503
        for _ in range(5):
            self.broker.db.execute("UPDATE deliveries SET next_try=0")
            self.broker.db.commit()
            self.broker.dispatch_once()
        deliveries = [r for r in self.receiver.records if r[0].get("name")]
        self.assertEqual(len(deliveries), 3)
        self.assertEqual(len({r[0]["eventId"] for r in deliveries}), 1)

    def test_fail_closed_callback_secret_scope_and_transport(self):
        for change in (
            {"secret": "whsec_bad"},
            {"url": "https://127.0.0.1/callback"},
            {"mode": "polling"},
        ):
            params = subscription()
            params["delivery"].update(change)
            with self.assertRaises(EventError):
                self.broker.rpc("events/subscribe", params)
        self.receiver.challenge_ok = False
        with self.assertRaises(EventError) as error:
            self.broker.rpc("events/subscribe", subscription())
        self.assertEqual(error.exception.code, -32015)
        self.assertEqual(
            self.broker.db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0
        )
        task = self.create()
        with self.assertRaises(EventError):
            self.broker.rpc(
                "events/subscribe", subscription("task.updated", {"task_id": task["task_id"]})
            )

    def test_restart_retry_stable_ids_rotation_expiry_and_revocation(self):
        params = subscription()
        sid = self.broker.rpc("events/subscribe", params)["id"]
        self.create()
        self.receiver.status = 503
        self.broker.dispatch_once()
        first_id = self.receiver.records[-1][0]["eventId"]
        self.broker.db.close()
        self.broker = EventBroker(self.path, self.verifier, self.receiver)
        new_secret = "whsec_" + base64.b64encode(b"other-synthetic-key-32-bytes!!!!!").decode()
        self.broker.rpc("events/subscribe", subscription(secret=new_secret))
        self.broker.db.execute("UPDATE deliveries SET next_try=0")
        self.broker.db.commit()
        self.receiver.status = 200
        self.broker.dispatch_once()
        self.assertEqual(self.receiver.records[-1][0]["eventId"], first_id)
        self.assertEqual(len(self.receiver.records[-1][1]["webhook-signature"].split()), 2)
        self.store.remove_agent(self.room["id"], "event-worker")
        count = len(self.receiver.records)
        self.broker.dispatch_once()
        self.assertEqual(len(self.receiver.records), count)
        self.broker.cleanup(time.time())
        self.assertIsNone(
            self.broker.db.execute("SELECT id FROM subscriptions WHERE id=?", (sid,)).fetchone()
        )

    def test_expiration_and_410_413_never_retry(self):
        params = subscription()
        params["ttlMs"] = 1
        self.broker.rpc("events/subscribe", params)
        time.sleep(0.01)
        self.broker.dispatch_once()
        self.assertEqual(
            self.broker.db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0
        )
        for index, status in enumerate((413, 410)):
            self.broker.rpc("events/subscribe", subscription())
            self.create("status-" + str(index))
            self.receiver.status = status
            self.broker.dispatch_once()
            self.assertEqual(
                self.broker.db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 0
            )

    def test_origin_updates_do_not_self_trigger_or_leak_to_workers(self):
        task = self.create()
        self.current = self.origin
        self.broker.rpc(
            "events/subscribe", subscription("task.updated", {"task_id": task["task_id"]})
        )
        self.store.handoffs.operate(
            self.room["id"],
            "bot:event-origin",
            "context",
            {"task_id": task["task_id"], "body": "own edit", "request_id": "context"},
        )
        self.broker.dispatch_once()
        self.assertEqual(len(self.receiver.records), 1)
        assignment = self.store.handoffs.inbox(self.room["id"], "bot:event-worker")[0]
        claim = self.store.handoffs.operate(
            self.room["id"],
            "bot:event-worker",
            "claim",
            {
                "task_id": task["task_id"],
                "assignment_id": assignment["id"],
                "expected_attempt": 0,
                "request_id": "claim",
            },
        )
        self.store.handoffs.operate(
            self.room["id"],
            "bot:event-worker",
            "update",
            {**claim, "kind": "completed", "body": "private result", "request_id": "result"},
        )
        self.broker.dispatch_once()
        self.assertEqual(self.receiver.records[-1][0]["name"], "task.updated")

    @patch.dict("os.environ", {}, clear=True)
    @patch("event_delivery.PinnedHTTPSConnection")
    def test_callback_ssrf_rebinding_and_redirect_are_blocked(self, connection):
        transport = CallbackTransport(["callback.example.com"])
        for ip in ("127.0.0.1", "169.254.169.254", "::1", "224.0.0.1", "240.0.0.1"):
            with patch(
                "event_delivery.socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443))]
            ):
                with self.assertRaises(ValueError):
                    transport.post("https://callback.example.com/x", b"{}", {})
        connection.assert_not_called()
        connection.return_value.getresponse.return_value.status = 302
        connection.return_value.getresponse.return_value.read.return_value = b""
        with patch(
            "event_delivery.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]
        ):
            status, _ = transport.post("https://callback.example.com/x", b"{}", {})
        self.assertEqual(status, 302)
        self.assertEqual(connection.return_value.request.call_count, 1)

    def test_slow_callback_does_not_block_healthy_delivery_or_unsubscribe(self):
        slow, healthy = subscription(), subscription()
        slow["delivery"]["url"] += "/slow"
        healthy["delivery"]["url"] += "/healthy"
        sid = self.broker.rpc("events/subscribe", slow)["id"]
        self.broker.rpc("events/subscribe", healthy)
        entered, release, delivered = threading.Event(), threading.Event(), threading.Event()
        original = self.receiver.post

        def post(url, body, headers):
            if json.loads(body).get("name"):
                if url.endswith("/slow"):
                    entered.set()
                    release.wait(3)
                    return 503, b"{}"
                delivered.set()
            return original(url, body, headers)

        self.receiver.post = post
        self.create()
        scan = threading.Thread(target=self.broker.dispatch_once)
        scan.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertTrue(delivered.wait(1))
            del slow["delivery"]["secret"]
            began = time.monotonic()
            self.broker.rpc("events/unsubscribe", slow)
            self.assertLess(time.monotonic() - began, 0.5)
        finally:
            release.set()
            scan.join(5)
        self.assertFalse(scan.is_alive())
        self.assertIsNone(
            self.broker.db.execute("SELECT 1 FROM subscriptions WHERE id=?", (sid,)).fetchone()
        )
        self.assertIsNone(
            self.broker.db.execute(
                "SELECT 1 FROM deliveries WHERE subscription=?", (sid,)
            ).fetchone()
        )

    def test_unsubscribe_invalidates_inflight_verification(self):
        entered, release = threading.Event(), threading.Event()
        original = self.receiver.post
        failures = []

        def post(url, body, headers):
            entered.set()
            release.wait(3)
            return original(url, body, headers)

        self.receiver.post = post

        def subscribe():
            try:
                self.broker.rpc("events/subscribe", subscription())
            except EventError as exc:
                failures.append(exc.reason)

        thread = threading.Thread(target=subscribe)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            params = subscription()
            del params["delivery"]["secret"]
            self.broker.rpc("events/unsubscribe", params)
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(failures, ["subscription_changed"])
        self.assertEqual(
            self.broker.db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0
        )

    @patch.dict("os.environ", {}, clear=True)
    def test_total_callback_deadline_and_bounded_stuck_dns(self):
        transport = CallbackTransport(["callback.example.com"], deadline_seconds=0.05)
        release = threading.Event()

        def dns(*args, **kwargs):
            release.wait(3)
            return [(2, 1, 6, "", ("8.8.8.8", 443))]

        with (
            patch("event_delivery.socket.getaddrinfo", side_effect=dns),
            patch("event_delivery.PinnedHTTPSConnection") as connection,
        ):
            try:
                for _ in range(5):
                    began = time.monotonic()
                    with self.assertRaises(TimeoutError):
                        transport.post("https://callback.example.com/x", b"{}", {})
                    self.assertLess(time.monotonic() - began, 0.4)
                connection.assert_not_called()
            finally:
                release.set()
                time.sleep(0.1)
        with (
            patch(
                "event_delivery.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]
            ),
            patch("event_delivery.PinnedHTTPSConnection") as connection,
        ):

            def trickle(size):
                for _ in range(30):
                    time.sleep(0.01)
                return b"{}"

            connection.return_value.getresponse.return_value.read.side_effect = trickle
            with self.assertRaises(TimeoutError):
                transport.post("https://callback.example.com/x", b"{}", {})
            connection.return_value.sock.shutdown.assert_called_once()
            time.sleep(0.35)

    def test_real_sdk_http_initialize_and_events_extension_on_same_auth_endpoint(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        app = build_http_app(
            self.base,
            self.grants,
            port,
            events_db=str(Path(self.temp.name) / "http-events.db"),
            event_transport=self.receiver,
        )
        http_server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
        thread = threading.Thread(target=http_server.run, kwargs={"sockets": [sock]})
        thread.start()
        for _ in range(500):
            if http_server.started:
                break
            time.sleep(0.01)

        async def exercise():
            url = f"http://127.0.0.1:{port}/mcp"
            async with AsyncExitStack() as stack:
                client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        trust_env=False, headers={"Authorization": "Bearer " + self.worker["token"]}
                    )
                )
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(url, http_client=client)
                )
                session = await stack.enter_async_context(ClientSession(read, write))
                init = await session.initialize()
                self.assertIn("events", init.capabilities.model_dump())
                self.assertIn("create_task", [t.name for t in (await session.list_tools()).tools])
                headers = {
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-03-26",
                }
                result = await client.post(
                    url,
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": 2, "method": "events/list", "params": {}},
                )
                self.assertEqual(len(result.json()["result"]["events"]), 2)
                result = await client.post(
                    url,
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "events/subscribe",
                        "params": subscription(),
                    },
                )
                self.assertIn("id", result.json()["result"])
                denied = await client.post(
                    url,
                    headers={**headers, "Authorization": "Bearer invalid"},
                    json={"jsonrpc": "2.0", "id": 4, "method": "events/list"},
                )
                self.assertEqual(denied.status_code, 401)
                self.create("http-event")
                for _ in range(300):
                    if any(r[0].get("name") == "handoff.available" for r in self.receiver.records):
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(
                    any(r[0].get("name") == "handoff.available" for r in self.receiver.records)
                )

        try:
            asyncio.run(exercise())
        finally:
            http_server.should_exit = True
            thread.join(10)
            self.assertFalse(thread.is_alive())
