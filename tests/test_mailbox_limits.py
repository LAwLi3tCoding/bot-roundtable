import unittest
from unittest.mock import patch

from roundtable import Problem, Store
from ui_sessions import UISessions


class MailboxLimitsTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("Synthetic workspace")["id"]
        for aid in ("dot", "grok"):
            self.store.add_agent(self.room, aid, "mailbox")

    def tearDown(self):
        self.store.db.close()

    def create(self, members, request="one"):
        return self.store.mailboxes.create(
            self.room, "user", dict(title="Synthetic", members=members, request_id=request)
        )

    def test_bare_and_prefixed_members(self):
        self.assertIn("bot:dot", self.create(["dot"])["members"])
        self.assertIn("bot:dot", self.create(["bot:dot"], "two")["members"])
        with self.assertRaises(Problem) as error:
            self.create(["nobody"], "three")
        self.assertEqual(error.exception.status, 400)
        self.assertIn("不认识成员 nobody", str(error.exception))

    def test_worker_wakes_and_hourly_recovery(self):
        topic = self.create(["dot", "grok"])["id"]
        with patch("roundtable.time.time", return_value=1000):
            self.store.grant(self.room, "dot", 1)
            self.store.mailboxes.post(
                self.room,
                "bot:dot",
                topic,
                dict(body="Hello", request_id="a", mentions=["bot:grok"]),
            )
            with self.assertRaisesRegex(Problem, "60 分钟后恢复"):
                self.store.mailboxes.post(
                    self.room,
                    "bot:dot",
                    topic,
                    dict(body="Again", request_id="b", mentions=["bot:grok"]),
                )
        with patch("roundtable.time.time", return_value=4601):
            self.store.mailboxes.post(
                self.room,
                "bot:dot",
                topic,
                dict(body="Recovered", request_id="b", mentions=["bot:grok"]),
            )
        self.assertEqual(len(self.store.mailboxes.wake_inbox(self.room, "bot:grok")["messages"]), 2)

    def test_new_worker_default(self):
        topic = self.create(["dot", "grok"])["id"]
        self.store.mailboxes.post(
            self.room, "bot:dot", topic, dict(body="Hello", request_id="a", mentions=["bot:grok"])
        )
        self.assertEqual(len(self.store.mailboxes.wake_inbox(self.room, "bot:grok")["messages"]), 1)

    def test_ui_scope_only_noncredential_admin(self):
        base = "/api/rooms/" + "a" * 24 + "/"
        for action in ("grant", "settings"):
            self.assertTrue(UISessions.permitted("POST", base + action))
            self.assertFalse(UISessions.permitted("DELETE", base + action))
        for path in (base + "join", base + "remove", "/api/bots", "/api/rooms"):
            self.assertFalse(UISessions.permitted("POST", path))

    def test_topic_edits_restrict_bots_and_revoke_removed_access(self):
        topic = self.create(["dot", "grok"])["id"]
        with self.assertRaises(Problem):
            self.store.mailboxes.update(self.room, "bot:dot", topic, {"title": "Changed"})
        result = self.store.mailboxes.update(
            self.room, "user", topic, {"title": "Changed", "members": ["user", "dot"]}
        )
        self.assertEqual(result["title"], "Changed")
        with self.assertRaises(Problem):
            self.store.mailboxes.messages(self.room, "bot:grok", topic)

    def test_member_edit_atomicity_and_replacement_identity(self):
        topic = self.create(["dot", "grok"])["id"]
        with self.assertRaises(Problem):
            self.store.mailboxes.update(
                self.room, "user", topic, {"title": "Bad", "members": ["user", "nobody"]}
            )
        self.assertEqual(self.store.mailboxes.topics(self.room, "user")[0]["title"], "Synthetic")
        self.store.remove_agent(self.room, "dot")
        self.store.add_agent(self.room, "dot", "mailbox")
        with self.assertRaises(Problem):
            self.store.mailboxes.messages(self.room, "bot:dot", topic)
        self.store.mailboxes.update(self.room, "user", topic, {"members": ["user", "dot"]})
        self.assertEqual(self.store.mailboxes.messages(self.room, "bot:dot", topic)["messages"], [])

    def test_state_refresh_finishes_transaction(self):
        self.store.state(self.room)
        self.assertFalse(self.store.db.in_transaction)
        self.store.grant(self.room, "dot", 0)
        self.store.state(self.room)
        self.assertEqual(
            next(a for a in self.store.state(self.room)["agents"] if a["id"] == "dot")["allowance"],
            0,
        )

    def test_shared_roundtable_and_private_history_boundary(self):
        private = self.create(["dot"])["id"]
        shared = self.store.mailboxes.roundtable(self.room)
        self.assertNotEqual(shared["id"], private)
        self.assertEqual(shared["id"], self.store.mailboxes.roundtable(self.room, "bot:dot")["id"])
        self.store.add_agent(self.room, "third")
        self.assertIn("bot:third", self.store.mailboxes.roundtable(self.room)["members"])
        with self.assertRaises(Problem):
            self.store.mailboxes.messages(self.room, "bot:third", private)
        self.store.mailboxes.post(
            self.room, "user", shared["id"], dict(body="Silent", request_id="quiet")
        )
        self.assertEqual(self.store.mailboxes.wake_inbox(self.room, "bot:dot")["messages"], [])
        self.store.mailboxes.post(
            self.room,
            "user",
            shared["id"],
            dict(body="Notify", request_id="wake", mentions=["bot:dot"]),
        )
        self.assertEqual(len(self.store.mailboxes.wake_inbox(self.room, "bot:dot")["messages"]), 1)
        self.assertEqual(self.store.mailboxes.wake_inbox(self.room, "bot:grok")["messages"], [])
