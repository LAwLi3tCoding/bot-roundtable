import unittest
from unittest.mock import patch
from roundtable import Store


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

    def allowance(self, bot):
        return self.store.db.execute(
            "SELECT allowance FROM agents WHERE room=? AND id=?", (self.room, bot)
        ).fetchone()[0]

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
        topic = self.store.mailboxes.create(
            self.room,
            "user",
            {"members": ["bot:alpha"], "title": "Synthetic", "request_id": "topic"},
        )["id"]
        root = self.store.mailboxes.post(
            self.room,
            "user",
            topic,
            {"body": "Synthetic", "request_id": "msg", "mentions": ["bot:alpha"]},
        )
        result = feed(
            self.room,
            "bot:alpha",
            {"name": "roundtable.notification", "arguments": {}, "after": cursor},
        )
        self.assertEqual(result["events"][0]["data"], {"kind": "message", "id": str(root["id"])})
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
