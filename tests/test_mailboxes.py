import unittest
from roundtable import Store, Problem


class MailboxTest(unittest.TestCase):
    def setUp(self):
        self.s = Store()
        self.room = self.s.room("synthetic")["id"]
        for bot in ("alpha", "bravo", "charlie"):
            self.s.add_agent(self.room, bot, "mailbox")
            self.s.grant(self.room, bot, 20)
        self.m = self.s.mailboxes
        self.topic = self.m.create(
            self.room,
            "bot:alpha",
            {"title": "Private", "members": ["bot:bravo"], "request_id": "create", "budget": 2},
        )["id"]

    def tearDown(self):
        self.s.db.close()

    def post(self, actor="bot:alpha", **data):
        return self.m.post(
            self.room, actor, self.topic, {"body": "Synthetic message", "request_id": "one", **data}
        )

    def test_delivery_not_wake_and_sender_not_unread(self):
        message = self.post()
        self.assertEqual(message["recipients"], ["bot:bravo"])
        self.assertEqual(self.m.inbox(self.room, "bot:alpha")["messages"], [])
        self.assertEqual(len(self.m.inbox(self.room, "bot:bravo")["messages"]), 1)
        self.assertEqual(self.m.wake_inbox(self.room, "bot:bravo")["messages"], [])
        self.assertEqual(self.m.topics(self.room, "bot:alpha")[0]["unread"], 0)
        self.assertEqual(self.m.topics(self.room, "bot:bravo")[0]["unread"], 1)
        self.m.read(self.room, "bot:bravo", self.topic, message["id"])
        self.assertEqual(self.m.topics(self.room, "bot:bravo")[0]["unread"], 0)

    def test_owner_atomic_join_and_history(self):
        self.post()
        self.assertEqual(len(self.m.messages(self.room, "user", self.topic)["messages"]), 1)
        with self.assertRaises(Problem):
            self.post("user")
        self.post("user", join=True)
        self.assertIn("user", self.m.topics(self.room, "user")[0]["members"])
        self.assertEqual(len(self.m.messages(self.room, "user", self.topic)["messages"]), 2)

    def test_scope_spoof_and_mentions_rejected(self):
        for data in (
            {"sender": "user"},
            {"recipients": ["bot:charlie"]},
            {"mentions": ["bot:charlie"]},
        ):
            with self.assertRaises(Problem):
                self.post(**data)
        with self.assertRaises(Problem):
            self.m.messages(self.room, "bot:charlie", self.topic)
        self.assertEqual(self.m.topics(self.room, "bot:charlie"), [])
        other = self.s.room("other")["id"]
        with self.assertRaises(Problem):
            self.m.messages(other, "user", self.topic)

    def test_replay_budget_stop(self):
        first = self.post(mentions=["bot:bravo"])
        self.assertEqual(first, self.post(mentions=["bot:bravo"]))
        self.assertEqual(len(self.m.wake_inbox(self.room, "bot:bravo")["messages"]), 1)
        with self.assertRaises(Problem):
            self.post(body="conflict")
        self.post("bot:bravo", request_id="two")
        with self.assertRaises(Problem):
            self.post(request_id="three")
        self.m.stop(self.room, "user", self.topic)
        self.assertEqual(self.m.wake_inbox(self.room, "bot:bravo")["messages"], [])
        with self.assertRaises(Problem):
            self.post("user", join=True)

    def test_credential_rotation_revokes_topic_and_delivery(self):
        self.post(mentions=["bot:bravo"])
        self.s.db.execute(
            "UPDATE agents SET token='rotated-synthetic' WHERE room=? AND id='bravo'", (self.room,)
        )
        self.assertEqual(self.m.inbox(self.room, "bot:bravo")["messages"], [])
        self.assertEqual(self.m.topics(self.room, "bot:bravo"), [])
        with self.assertRaises(Problem):
            self.m.messages(self.room, "bot:bravo", self.topic)

    def test_state_no_legacy_room_discussion_disclosure(self):
        self.s.discussions.post(self.room, "user", {"body": "legacy", "request_id": "legacy"})
        self.assertEqual(self.s.state(self.room, "bot:alpha")["discussion_messages"], [])

    def test_human_turn_renews_budget_but_replay_does_not(self):
        self.post()
        self.post("bot:bravo", request_id="two")
        self.post("user", join=True, request_id="human")
        self.post(request_id="three")
        self.post("user", join=True, request_id="human")
        self.assertEqual(self.m.topics(self.room, "user")[0]["used"], 1)
        self.post("bot:bravo", request_id="four")
        with self.assertRaises(Problem):
            self.post(request_id="five")

    def test_bot_new_topic_requires_finite_initiation_allowance(self):
        self.s.grant(self.room, "charlie", 0)
        with self.assertRaises(Problem):
            self.m.create(
                self.room,
                "bot:charlie",
                {"title": "New", "members": ["bot:alpha"], "request_id": "new"},
            )

    def test_human_default_wakes_members_and_replay_is_stable(self):
        first = self.post("user", join=True)
        self.assertEqual(first["mentions"], ["bot:alpha", "bot:bravo"])
        self.assertEqual(first, self.post("user", join=True))
        for actor in ("bot:alpha", "bot:bravo"):
            self.assertEqual(len(self.m.wake_inbox(self.room, actor)["messages"]), 1)
        silent = self.post("user", request_id="silent", mentions=[])
        self.assertEqual(silent["mentions"], [])
        self.assertEqual(len(self.m.wake_inbox(self.room, "bot:alpha")["messages"]), 1)
