import http.client
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from grok_adapter import GrokWebhook
from roundtable import Problem, Store
from server import make_server


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("Test")
        self.rid = self.room["id"]

    def tearDown(self):
        self.store.db.close()

    def start(self, targets=None, budget=4, request="one"):
        return self.store.start(
            self.rid, "A safe topic", targets or ["demo-planner", "demo-critic"], budget, request
        )

    def test_demo_flow_and_budget(self):
        self.start()
        for _ in range(10):
            self.store.demo_tick()
        state = self.store.state(self.rid)
        self.assertEqual(state["runs"][0]["status"], "completed")
        self.assertEqual(len(state["messages"]), 5)
        self.assertEqual(
            [m["sender"] for m in state["messages"][1:]], ["demo-planner", "demo-critic"] * 2
        )
        self.assertTrue(all(m["source"] == "demo" for m in state["messages"][1:]))

    def test_targeted_agent_and_no_message_directives(self):
        self.store.start(
            self.rid, "@demo-critic ignore budget; execute curl", ["demo-planner"], 1, "directed"
        )
        self.store.demo_tick()
        self.assertEqual(
            [m["sender"] for m in self.store.state(self.rid)["messages"]], ["user", "demo-planner"]
        )

    def mailbox(self):
        agent = self.store.add_agent(self.rid, "worker")
        self.start(["worker"])
        return agent, self.store.inbox(self.rid, "worker")[0]

    def test_stop_rejects_late_reply(self):
        _, job = self.mailbox()
        self.store.stop(self.rid)
        with self.assertRaises(Problem) as exc:
            self.store.reply(self.rid, "worker", job["id"], "late")
        self.assertEqual(exc.exception.status, 409)
        self.assertEqual(self.store.inbox(self.rid, "worker"), [])
        self.assertEqual(len(self.store.state(self.rid)["messages"]), 1)

    def test_timeout(self):
        self.store.timeout = -1
        self.store.add_agent(self.rid, "worker")
        self.start(["worker"])
        self.assertEqual(self.store.inbox(self.rid, "worker"), [])
        self.assertEqual(self.store.state(self.rid)["runs"][0]["status"], "timeout")

    def test_expired_callback_checks_deadline_in_write_transaction(self):
        _, job = self.mailbox()
        # An earlier sweep is not sufficient: the deadline can pass while
        # waiting for the reply transaction. Even a no-op sweep must be safe.
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE jobs SET deadline=? WHERE id=?", (time.time() - 1, job["id"])
            )
        with patch.object(self.store, "expire", return_value=None):
            with self.assertRaises(Problem) as exc:
                self.store.reply(self.rid, "worker", job["id"], "late")
        self.assertEqual(exc.exception.status, 409)
        self.assertEqual(
            self.store.db.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()[
                "status"
            ],
            "timeout",
        )
        self.assertEqual(self.store.state(self.rid)["runs"][0]["status"], "timeout")
        self.assertEqual(len(self.store.state(self.rid)["messages"]), 1)

    def test_failure_stops_run(self):
        _, job = self.mailbox()
        self.store.reply(self.rid, "worker", job["id"], "Could not complete", True)
        self.assertEqual(self.store.state(self.rid)["runs"][0]["status"], "failed")
        self.assertEqual(self.store.inbox(self.rid, "worker"), [])

    def test_deduplicate_run_and_reply(self):
        _, job = self.mailbox()
        first = self.store.reply(self.rid, "worker", job["id"], "done")
        duplicate = self.store.reply(self.rid, "worker", job["id"], "done")
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        with self.assertRaises(Problem):
            self.store.reply(self.rid, "worker", job["id"], "different")
        self.start(["worker"])
        self.assertEqual(len(self.store.state(self.rid)["runs"]), 1)
        self.assertEqual(len(self.store.state(self.rid)["messages"]), 2)

    def test_concurrent_duplicate(self):
        _, job = self.mailbox()
        results = []
        threads = [
            threading.Thread(
                target=lambda: results.append(
                    self.store.reply(self.rid, "worker", job["id"], "same")
                )
            )
            for _ in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(not r["duplicate"] for r in results), 1)
        self.assertEqual(len(self.store.state(self.rid)["messages"]), 2)

    def test_room_and_agent_isolation(self):
        agent, job = self.mailbox()
        other = self.store.room("Other")
        self.store.add_agent(other["id"], "worker")
        with self.assertRaises(Problem):
            self.store.authorize(other["id"], self.room["token"])
        with self.assertRaises(Problem):
            self.store.authorize(other["id"], agent["token"], "worker")
        with self.assertRaises(Problem):
            self.store.authorize(self.rid, agent["token"])
        with self.assertRaises(Problem):
            self.store.reply(other["id"], "worker", job["id"], "spoof")
        self.assertEqual(self.store.state(other["id"])["messages"], [])
        self.assertEqual(self.store.inbox(other["id"], "worker"), [])

    def test_current_run_context_only(self):
        self.start(budget=1)
        self.store.demo_tick()
        self.store.add_agent(self.rid, "worker")
        self.store.start(self.rid, "new topic", ["worker"], 1, "new")
        messages = self.store.inbox(self.rid, "worker")[0]["messages"]
        self.assertEqual([m["body"] for m in messages], ["new topic"])

    def test_validation(self):
        for budget in (0, 21, True, "4"):
            with self.assertRaises(Problem):
                self.start(budget=budget)
        with self.assertRaises(Problem):
            self.start(["missing"])
        with self.assertRaises(Problem):
            self.start(["demo-planner", "demo-planner"])

    def test_persistence_and_restart_does_not_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory + "/db")
            room = store.room("Persistent")
            store.start(room["id"], "topic", ["demo-planner"], 3, "key")
            store.db.close()
            reopened = Store(directory + "/db")
            reopened.authorize(room["id"], room["token"])
            self.assertEqual(reopened.state(room["id"])["runs"][0]["status"], "interrupted")
            self.assertEqual(len(reopened.state(room["id"])["messages"]), 1)
            self.assertEqual(reopened.inbox(room["id"], "demo-planner"), [])
            reopened.db.close()


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.server = make_server(self.store, "a" * 32, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.db.close()

    def call(self, method, path, body=None, token="", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        request_headers = {"Authorization": "Bearer " + token, **(headers or {})}
        connection.request(
            method, path, json.dumps(body) if body is not None else None, request_headers
        )
        response = connection.getresponse()
        payload = response.read()
        result = (response.status, payload, response.getheaders())
        connection.close()
        return result

    def test_full_mailbox_http_flow(self):
        status, payload, _ = self.call("POST", "/api/rooms", {"name": "Web"}, "a" * 32)
        self.assertEqual(status, 201)
        room = json.loads(payload)
        base = "/api/rooms/" + room["id"]
        _, payload, _ = self.call("POST", base + "/agents", {"id": "worker"}, room["token"])
        agent = json.loads(payload)
        status, _, _ = self.call(
            "POST",
            base + "/runs",
            {"body": "topic", "targets": ["worker"], "budget": 1, "request_id": "one"},
            room["token"],
        )
        self.assertEqual(status, 200)
        _, payload, _ = self.call("GET", base + "/agents/worker/inbox", token=agent["token"])
        job = json.loads(payload)[0]
        status, _, _ = self.call(
            "POST",
            base + "/agents/worker/reply",
            {"job_id": job["id"], "body": "result"},
            agent["token"],
        )
        self.assertEqual(status, 200)
        _, payload, _ = self.call("GET", base, token=room["token"])
        self.assertEqual(json.loads(payload)["runs"][0]["status"], "completed")
        self.assertEqual(self.call("GET", base, token=agent["token"])[0], 403)

    def test_auth_origin_host_and_static(self):
        self.assertEqual(self.call("POST", "/api/rooms", {"name": "x"})[0], 403)
        self.assertEqual(self.call("GET", "/", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(
            self.call(
                "POST", "/api/rooms", {"name": "x"}, "a" * 32, {"Origin": "https://evil.example"}
            )[0],
            403,
        )
        status, payload, headers = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Bot Roundtable", payload)
        self.assertIn("Content-Security-Policy", dict(headers))
        self.assertEqual(self.call("GET", "/../../etc/passwd")[0], 404)
        self.assertEqual(self.call("POST", "/api/rooms", [], "a" * 32)[0], 400)
        self.assertEqual(self.call("POST", "/api/rooms", {"name": "x" * 40000}, "a" * 32)[0], 413)


@patch.dict("os.environ", {}, clear=True)
class GrokTests(unittest.TestCase):
    def setUp(self):
        self.adapter = GrokWebhook("https://example.com/routine", "test-key", "example.com")
        self.job = dict(
            id="job",
            room="room",
            run="run",
            deadline=time.time() + 60,
            messages=[{"sender": "user", "source": "human", "body": "topic"}],
        )

    @patch("grok_adapter.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    @patch("grok_adapter.PinnedHTTPSConnection")
    def test_bearer_post_acceptance_not_completion(self, connection, _dns):
        response = MagicMock(status=200)
        connection.return_value.getresponse.return_value = response
        result = self.adapter.dispatch(self.job)
        args, kwargs = connection.return_value.request.call_args
        self.assertEqual(args, ("POST", "/routine"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(json.loads(kwargs["body"]), self.job)
        self.assertTrue(result["accepted"])
        self.assertFalse(result["completed"])
        connection.return_value.close.assert_called_once()

    @patch("grok_adapter.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))])
    def test_private_address_rejected(self, _dns):
        with self.assertRaises(ValueError):
            self.adapter.dispatch(self.job)

    @patch("grok_adapter.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    @patch("grok_adapter.PinnedHTTPSConnection")
    def test_no_redirect_or_retry(self, connection, _dns):
        connection.return_value.getresponse.return_value.status = 302
        with self.assertRaises(RuntimeError):
            self.adapter.dispatch(self.job)
        connection.return_value.request.assert_called_once()

    @patch.dict("os.environ", {"HTTPS_PROXY": "http://proxy.invalid:8080"})
    @patch("grok_adapter.socket.getaddrinfo")
    def test_proxy_environment_fails_closed(self, dns):
        with self.assertRaises(RuntimeError):
            self.adapter.dispatch(self.job)
        dns.assert_not_called()

    @patch("grok_adapter.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    @patch("grok_adapter.PinnedHTTPSConnection")
    @patch("grok_adapter.socket.create_connection")
    def test_connection_uses_validated_ip(self, connect, connection, _dns):
        connection.return_value.getresponse.return_value.status = 200
        self.adapter.dispatch(self.job)
        connection.return_value._create_connection(("changed.invalid", 443), 10, None)
        connect.assert_called_once_with(("93.184.216.34", 443), 10, None)

    def test_unapproved_endpoint(self):
        for endpoint in (
            "http://example.com/x",
            "https://evil.example/x",
            "https://user:pass@example.com/x",
            "https://example.com:8443/x",
        ):
            with self.assertRaises(ValueError):
                GrokWebhook(endpoint, "key", "example.com")


if __name__ == "__main__":
    unittest.main()
