"""Independent adversarial review of mailbox concurrency and authorization."""

from concurrent.futures import ThreadPoolExecutor
import unittest

from roundtable import Problem, Store


class MailboxSecurityReview(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("synthetic")["id"]
        for bot in ("alpha", "bravo", "charlie"):
            self.store.add_agent(self.room, bot)
            self.store.grant(self.room, bot, 20)
        self.mail = self.store.mailboxes
        self.creation = dict(title="Private", members=["bot:bravo"], request_id="create", budget=2)
        self.topic = self.mail.create(self.room, "bot:alpha", self.creation)["id"]

    def tearDown(self):
        self.store.db.close()

    def post(self, request="send", actor="bot:alpha", **extra):
        return self.mail.post(
            self.room, actor, self.topic, dict(body="Synthetic", request_id=request, **extra)
        )

    def test_concurrent_budget_cannot_overdraw(self):
        def send(index):
            try:
                return self.post(str(index))
            except Problem as exc:
                self.assertEqual(exc.status, 409)
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(send, range(16)))
        self.assertEqual(sum(result is not None for result in results), 2)
        self.assertEqual(len(self.mail.inbox(self.room, "bot:bravo")["messages"]), 2)

    def test_concurrent_replay_delivers_and_charges_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.post(mentions=["bot:bravo"]), range(16)))
        self.assertEqual(len({result["id"] for result in results}), 1)
        self.assertEqual(self.mail.topics(self.room, "bot:alpha")[0]["used"], 1)
        self.assertEqual(len(self.mail.wake_inbox(self.room, "bot:bravo")["messages"]), 1)

    def test_create_replay_survives_atomic_owner_join(self):
        self.post(actor="user", join=True)
        replay = self.mail.create(self.room, "bot:alpha", self.creation)
        self.assertEqual(replay["id"], self.topic)
        self.assertIn("user", replay["members"])
        self.assertNotIn("initial_members", replay)

    def test_revoked_recreated_sender_cannot_replay_old_topic(self):
        self.post()
        self.store.remove_agent(self.room, "alpha")
        self.store.add_agent(self.room, "alpha")
        with self.assertRaises(Problem):
            self.mail.create(self.room, "bot:alpha", self.creation)
        with self.assertRaises(Problem):
            self.post()
        self.assertEqual(self.mail.inbox(self.room, "bot:alpha")["messages"], [])

    def test_nonmember_cannot_stop_private_topics_through_legacy_stop(self):
        with self.assertRaises(Problem):
            self.store.stop_peer(self.room, "charlie")
        self.assertFalse(self.mail.topics(self.room, "user")[0]["stopped"])

    def test_exhausted_private_topic_cannot_be_stopped_by_outsider(self):
        self.post("one")
        self.post("two")
        with self.assertRaises(Problem):
            self.store.stop_peer(self.room, "charlie")
        self.assertFalse(self.mail.topics(self.room, "user")[0]["stopped"])

    def test_failed_join_rolls_back_membership_and_budget(self):
        with self.assertRaises(Problem):
            self.post(actor="user", join=True, mentions=["bot:charlie"])
        topic = self.mail.topics(self.room, "user")[0]
        self.assertNotIn("user", topic["members"])
        self.assertEqual(topic["used"], 0)

    def test_identical_bot_names_in_other_scope_cannot_read(self):
        other = self.store.room("Other")["id"]
        self.store.add_agent(other, "alpha")
        self.post()
        with self.assertRaises(Problem):
            self.mail.messages(other, "bot:alpha", self.topic)
        self.assertEqual(self.mail.inbox(other, "bot:alpha")["messages"], [])
