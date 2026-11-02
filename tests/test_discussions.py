import unittest
from unittest.mock import patch
from roundtable import Store, Problem


class DiscussionsTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("synthetic")["id"]
        self.store.add_agent(self.room, "alpha", "mailbox")
        self.store.add_agent(self.room, "bravo", "mailbox")
        self.store.grant(self.room, "alpha", 20)
        self.store.grant(self.room, "bravo", 20)
        self.discussions = self.store.discussions

    def tearDown(self):
        self.store.db.close()

    def post(self, actor="user", **values):
        return self.discussions.post(
            self.room, actor, {"body": "synthetic", "request_id": "one", **values}
        )

    def test_human_broadcast_and_bot_plain_no_wake(self):
        root = self.post()
        for bot in ("alpha", "bravo"):
            self.assertEqual(
                len(self.discussions.inbox(self.room, "bot:" + bot, {})["messages"]), 1
            )
        self.post("bot:alpha", reply_to=root["id"])
        self.assertEqual(len(self.discussions.inbox(self.room, "bot:bravo", {})["messages"]), 1)

    def test_explicit_targets_replay_and_conflict(self):
        message = self.post(mentions=["alpha"])
        self.assertEqual(self.post(mentions=["alpha"]), message)
        self.assertEqual(self.discussions.inbox(self.room, "bot:bravo", {})["messages"], [])
        with self.assertRaises(Problem):
            self.post(mentions=["bravo"])
        with self.assertRaises(Problem):
            self.post(request_id="other", mentions=["outsider"])

    def test_reply_budget_counts_unmentioned_replies(self):
        root = self.post(budget=1)
        self.post("bot:alpha", reply_to=root["id"])
        with self.assertRaises(Problem):
            self.post("bot:bravo", reply_to=root["id"])

    def test_budget_range_and_inheritance(self):
        for value in (0, 21, True, "4"):
            with self.assertRaises(Problem):
                self.post(budget=value)
        root = self.post(budget=2)
        reply = self.post("bot:alpha", reply_to=root["id"], budget=20)
        self.assertEqual(int(reply["budget"]), 2)
        self.post("bot:bravo", reply_to=reply["id"], budget=20)
        with self.assertRaises(Problem):
            self.post("bot:alpha", request_id="third", reply_to=root["id"], budget=20)

    def test_connection_activity_is_epoch_scoped(self):
        root = self.post()
        self.post("bot:alpha", reply_to=root["id"])
        status = {row["id"]: row for row in self.store.connections.status(self.room)}
        self.assertIsNotNone(status["alpha"]["last_reply"])
        self.assertIsNone(status["bravo"]["last_reply"])
        self.assertEqual(status["alpha"]["subscription_state"], "unknown")
        self.assertNotIn("token", status["alpha"])
        self.assertNotIn("sender_epoch", self.discussions.listing(self.room)[-1])
        self.store.db.execute(
            "UPDATE agents SET token='new-epoch' WHERE room=? AND id='alpha'", (self.room,)
        )
        status = {row["id"]: row for row in self.store.connections.status(self.room)}
        self.assertIsNone(status["alpha"]["last_reply"])

    def test_modes_require_explicit_stop_and_cannot_cross_consume(self):
        root = self.post(budget=2)
        with self.assertRaises(Problem):
            self.store.start(self.room, "run", ["alpha"], 2, "run-one")
        with self.assertRaises(Problem):
            self.store.stop_peer(self.room, "alpha")
        self.assertTrue(self.store.state(self.room)["discussion_active"])
        self.store.stop(self.room)
        self.assertFalse(self.store.state(self.room)["discussion_active"])
        self.assertEqual(self.discussions.inbox(self.room, "bot:alpha", {})["messages"], [])
        self.assertGreater(
            self.store.db.execute(
                "SELECT COUNT(*) FROM discussion_mentions WHERE room=?", (self.room,)
            ).fetchone()[0],
            0,
        )
        run = self.store.start(self.room, "run", ["alpha"], 2, "run-one")
        self.assertEqual(run["status"], "running")
        with self.assertRaises(Problem):
            self.post(request_id="second-root")
        self.store.stop(self.room)
        with self.assertRaises(Problem):
            self.post("bot:alpha", reply_to=root["id"])
        self.post(request_id="second-root")

    def test_exhausted_root_allows_mode_switch(self):
        root = self.post(budget=1)
        self.post("bot:alpha", reply_to=root["id"])
        self.store.start(self.room, "run", ["alpha"], 1, "run-one")

    def test_notice_structure_progress_bound_and_replay(self):
        task = self.store.handoffs.create(
            self.room,
            "user",
            dict(
                title="Task title",
                context="context",
                assignments=[dict(worker="alpha", instruction="instruction")],
                budget=4,
                request_id="task",
            ),
        )
        tid = task["task_id"]
        assignment = self.store.db.execute(
            "SELECT id FROM assignments WHERE task=?", (tid,)
        ).fetchone()[0]
        with patch("discussions.time.time", return_value=120):
            for event in (50, 50, 51):
                self.discussions.system_notice(
                    tid,
                    assignment,
                    "bot:alpha",
                    "progress",
                    "line one\nline two\nline three",
                    event,
                )
        messages = self.discussions.listing(self.room)
        progress = [m for m in messages if m["notice"]["kind"] == "progress"]
        self.assertEqual(len(progress), 1)
        self.assertEqual(
            progress[0]["notice"],
            dict(
                kind="progress",
                actor="bot:alpha",
                task_title="Task title",
                worker="alpha",
                summary="",
            ),
        )
        self.assertEqual(self.discussions.inbox(self.room, "bot:alpha", {})["messages"], [])

    def test_connection_ttl_is_protocol_evidence_only(self):
        before = self.store.connections.status(self.room)[0]
        self.assertEqual(before["protocol_state"], "unknown")
        with patch("connections.time.time", return_value=100):
            self.store.connections.probe(self.room, "alpha", "synthetic-probe-nonce")
            row = next(r for r in self.store.connections.status(self.room) if r["id"] == "alpha")
            self.assertEqual(row["protocol_state"], "recent")
            self.assertEqual(row["activity_expires_at"], 220)
            self.assertFalse(row["vendor_account_verified"])
        with patch("connections.time.time", return_value=221):
            row = next(r for r in self.store.connections.status(self.room) if r["id"] == "alpha")
            self.assertEqual(row["protocol_state"], "stale")

    def test_events_use_scoped_cursor(self):
        feed = self.store.handoffs.event_feed
        cursor = feed(
            self.room,
            "bot:alpha",
            {"name": "roundtable.notification", "arguments": {}, "after": None},
        )["cursor"]
        root = self.post(mentions=["alpha"])
        result = feed(
            self.room,
            "bot:alpha",
            {"name": "roundtable.notification", "arguments": {}, "after": cursor},
        )
        self.assertEqual(result["events"][0]["data"], {"kind": "mention", "id": str(root["id"])})
        self.assertEqual(
            feed(
                self.room,
                "bot:bravo",
                {"name": "roundtable.notification", "arguments": {}, "after": cursor},
            )["events"],
            [],
        )

    def test_system_configuration_disabled(self):
        with patch.dict("os.environ", {"ROUNDTABLE_TASK_NOTICES": "0"}):
            self.discussions.system_notice("absent", "", "system", "delegated", "", 1)
        self.assertEqual(self.discussions.listing(self.room), [])
