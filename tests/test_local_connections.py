import json
import secrets
import threading
import time
import unittest
from unittest.mock import patch

from connections import capabilities
from grok_adapter import GrokWebhook
from local_client import LocalClient
from roundtable import Store
from server import make_server


class LocalConnectionTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("Local protocol")
        self.agent = self.store.add_agent(self.room["id"], "local-bot")
        self.server = make_server(self.store, secrets.token_urlsafe(32), port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.client = LocalClient(self.base, self.room["id"], self.agent["id"], self.agent["token"])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.db.close()

    def test_probe_scope_and_revocation_are_observed_not_vendor_inference(self):
        before = self.store.connections.status(self.room["id"])
        self.assertFalse(any(m["observed"] for m in before))
        result = self.client.call("probe")
        self.assertEqual(result["agent"], "local-bot")
        self.assertFalse(result["vendor_account_verified"])
        self.assertEqual(self.client.call("capabilities"), capabilities())
        self.assertTrue(any(m["observed"] for m in self.store.connections.status(self.room["id"])))
        self.store.remove_agent(self.room["id"], "local-bot")
        self.store.add_agent(self.room["id"], "local-bot")
        self.assertFalse(any(m["observed"] for m in self.store.connections.status(self.room["id"])))
        with self.assertRaises(ValueError):
            self.client.call("probe")

    def test_doctor_reports_transport_not_native_or_wake_and_does_not_write_probe(self):
        result = self.client.call("doctor")
        self.assertTrue(result["configured"]["verified"])
        self.assertTrue(result["transport_verified"]["verified"])
        self.assertFalse(result["native_roundtrip_verified"]["verified"])
        self.assertFalse(result["wake_verified"]["verified"])
        self.assertNotIn(self.agent["token"], json.dumps(result))
        self.assertFalse(any(m["observed"] for m in self.store.connections.status(self.room["id"])))

    def test_narrow_client_rejects_remote_urls_and_arbitrary_operations(self):
        for url in (
            "https://example.com",
            "http://127.0.0.1@evil.test",
            self.base + "/api",
            self.base + "?x=1",
        ):
            with self.assertRaises(ValueError):
                LocalClient(url, self.room["id"], self.agent["id"], self.agent["token"])
        with self.assertRaises(ValueError):
            self.client.call("../../settings")
        with self.assertRaises(ValueError):
            self.client.call("create", {"body": "x" * 32769})

    def test_local_client_uses_existing_assignment_flow(self):
        task = self.store.handoffs.create(
            self.room["id"],
            "user",
            {
                "title": "Local task",
                "context": "explicit context",
                "request_id": "local-task",
                "assignments": [{"worker": "local-bot", "instruction": "return one result"}],
            },
        )
        inbox = self.client.call("inbox")
        self.assertEqual(inbox[0]["task_id"], task["task_id"])
        claimed = self.client.call(
            "claim",
            {
                "task_id": task["task_id"],
                "assignment_id": inbox[0]["id"],
                "expected_attempt": 0,
                "request_id": "local-claim",
            },
        )
        result = self.client.call(
            "report",
            {
                **{k: claimed[k] for k in ("task_id", "assignment_id", "lease", "attempt")},
                "kind": "completed",
                "body": "protocol test",
                "request_id": "local-result",
            },
        )
        self.assertEqual(result["status"], "completed")

    @patch.object(GrokWebhook, "dispatch")
    def test_grok_assignment_wake_is_acceptance_only(self, dispatch):
        dispatch.return_value = {"accepted": True}
        adapter = GrokWebhook("https://example.com/routine", "test-key", "example.com")
        result = adapter.dispatch_assignment(
            {
                "id": "assignment",
                "task_id": "task",
                "room": self.room["id"],
                "origin": "bot:origin",
                "context": "shared",
                "instruction": "own",
                "status": "queued",
                "deadline": time.time() + 60,
            }
        )
        self.assertFalse(result["completed"])
        self.assertEqual(dispatch.call_args.args[0]["phase"], "assignment")
        self.assertNotIn(self.agent["token"], json.dumps(dispatch.call_args.args[0]))
        with self.assertRaises(ValueError):
            adapter.dispatch_assignment({"status": "completed"})
