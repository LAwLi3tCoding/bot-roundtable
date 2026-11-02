"""Regression tests for membership revocation, nested writes and identity scope."""

import http.client
import json
import threading
import unittest

from roundtable import Problem, Store
from server import make_server


class UpgradeSecurityTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(demo=True)

    def tearDown(self):
        self.store.db.close()

    def test_failed_second_join_rolls_back_entire_group(self):
        self.store.register_bot("alpha", "Alpha", "mailbox")
        self.store.register_bot("bravo", "Bravo", "mailbox")
        self.store.db.execute(
            "CREATE TRIGGER fail_bravo BEFORE INSERT ON agents WHEN NEW.id='bravo' "
            "BEGIN SELECT RAISE(ABORT,'synthetic insertion failure'); END"
        )
        with self.assertRaises(Problem):
            self.store.create_group("Atomic group", ["alpha", "bravo"])
        self.assertEqual(self.store.list_rooms(), [])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM agents").fetchone()[0], 0)

    def test_nested_rollback_preserves_outer_scope_until_outer_commit(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.room("Must roll back")
                raise RuntimeError("outer failure")
        self.assertEqual(self.store.list_rooms(), [])
        with self.store.transaction():
            self.store.room("Keep outer write")
            try:
                with self.store.transaction():
                    self.store.room("Rollback only inner write")
                    raise RuntimeError("inner failure")
            except RuntimeError:
                pass
        self.assertEqual([r["name"] for r in self.store.list_rooms()], ["Keep outer write"])

    def test_human_sender_id_is_reserved(self):
        room = self.store.room("Identities")
        with self.assertRaises(Problem):
            self.store.register_bot("user", "Human impersonator", "mailbox")
        with self.assertRaises(Problem):
            self.store.add_agent(room["id"], "user")

    def test_removed_and_rejoined_agent_cannot_resume_old_callback(self):
        room = self.store.room("Rejoin")
        self.store.register_bot("worker", "Worker", "mailbox")
        old = self.store.join(room["id"], "worker")
        self.store.start(room["id"], "topic", ["worker"], 1, "one")
        job = self.store.inbox(room["id"], "worker")[0]
        self.store.stop(room["id"])
        self.store.remove_agent(room["id"], "worker")
        fresh = self.store.join(room["id"], "worker")
        with self.assertRaises(Problem) as exc:
            self.store.authorize(room["id"], old["token"], "worker")
        self.assertEqual(exc.exception.status, 403)
        self.store.authorize(room["id"], fresh["token"], "worker")
        with self.assertRaises(Problem) as exc:
            self.store.reply(room["id"], "worker", job["id"], "old result")
        self.assertEqual(exc.exception.status, 409)
        self.assertEqual(len(self.store.state(room["id"])["messages"]), 1)

    def test_revocation_cannot_interleave_authentication_and_operation(self):
        room = self.store.room("Revocation race")
        self.store.register_bot("worker", "Worker", "mailbox")
        old = self.store.join(room["id"], "worker")
        self.store.grant(room["id"], "worker", 2)
        attempted = threading.Event()
        revoked = threading.Event()
        revoker_errors = []
        threads = []
        original = self.store.authorize
        intercept = True

        def revoke():
            attempted.set()
            try:
                self.store.stop(room["id"])
                self.store.remove_agent(room["id"], "worker")
                self.store.join(room["id"], "worker")
                self.store.grant(room["id"], "worker", 2)
                revoked.set()
            except Exception as exc:
                revoker_errors.append(exc)

        def authorize(rid, token, agent=None):
            nonlocal intercept
            original(rid, token, agent)
            if intercept and agent == "worker":
                intercept = False
                thread = threading.Thread(target=revoke)
                threads.append(thread)
                thread.start()
                self.assertTrue(attempted.wait(1))
                # The revoker must block until the authenticated operation is
                # finished, rather than replace its identity between the two.
                self.assertFalse(revoked.wait(0.05))

        self.store.authorize = authorize
        server = make_server(self.store, "a" * 32, port=0)
        serving = threading.Thread(target=server.serve_forever)
        serving.start()
        try:
            path = f"/api/rooms/{room['id']}/agents/worker/peer/runs"
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request(
                "POST",
                path,
                json.dumps(
                    dict(
                        body="bounded initiation",
                        targets=["demo-planner"],
                        budget=1,
                        request_id="one",
                    )
                ),
                {"Authorization": "Bearer " + old["token"]},
            )
            response = connection.getresponse()
            payload = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["actor"], "bot:worker")
            for thread in threads:
                thread.join(2)
                self.assertFalse(thread.is_alive())
            self.assertEqual(revoker_errors, [])
            self.assertTrue(revoked.is_set())
            # New membership allowance is untouched by the old request.
            member = next(a for a in self.store.state(room["id"])["agents"] if a["id"] == "worker")
            self.assertEqual(member["allowance"], 2)
            with self.assertRaises(Problem):
                original(room["id"], old["token"], "worker")
        finally:
            server.shutdown()
            server.server_close()
            serving.join()
            for thread in threads:
                thread.join(2)
