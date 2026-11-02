"""Independent synthetic mention boundary regressions."""

import unittest
from roundtable import Store


class DiscussionSecurityReview(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.addCleanup(self.store.db.close)
        self.store.register_bot("review-bot", "Review", "dot")

    def room(self):
        return self.store.create_group("Synthetic", ["review-bot"])["id"]

    def post(self, room, request):
        return self.store.discussions.post(
            room,
            "user",
            {
                "body": "Synthetic",
                "mentions": ["review-bot"],
                "request_id": request,
            },
        )

    def test_rate_limit_is_shared_across_rooms(self):
        first, second = self.room(), self.room()
        for i in range(10):
            self.post(first, str(i))
        self.post(second, "overflow")
        self.assertEqual(self.store.discussions.inbox(second, "bot:review-bot", {})["messages"], [])

    def test_rejoining_bot_does_not_inherit_unread_mentions(self):
        room = self.room()
        self.post(room, "before")
        self.store.remove_agent(room, "review-bot")
        self.store.join(room, "review-bot")
        self.assertEqual(self.store.discussions.inbox(room, "bot:review-bot", {})["messages"], [])

    def test_human_broadcast_and_bot_plain_reply_do_not_rebroadcast(self):
        room = self.room()
        self.store.register_bot("second-bot", "Second", "dot")
        self.store.join(room, "second-bot")
        root = self.store.discussions.post(
            room, "user", {"body": "Broadcast", "request_id": "root"}
        )
        for bot in ("review-bot", "second-bot"):
            self.assertEqual(
                len(self.store.discussions.inbox(room, "bot:" + bot, {})["messages"]), 1
            )
        self.store.discussions.post(
            room,
            "bot:review-bot",
            {
                "body": "Reply",
                "request_id": "reply",
                "reply_to": root["id"],
            },
        )
        self.assertEqual(
            len(self.store.discussions.inbox(room, "bot:second-bot", {})["messages"]), 1
        )

    def test_root_reply_budget_serializes_concurrent_replies(self):
        from concurrent.futures import ThreadPoolExecutor
        from roundtable import Problem

        room = self.room()
        root = self.post(room, "root")

        def reply(index):
            try:
                self.store.discussions.post(
                    room,
                    "bot:review-bot",
                    {
                        "body": "Reply",
                        "request_id": str(index),
                        "reply_to": root["id"],
                    },
                )
                return True
            except Problem as exc:
                self.assertEqual(exc.status, 409)
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(reply, range(12))), 4)

    def test_new_epoch_has_distinct_idempotency_scope(self):
        room = self.room()
        old = self.store.discussions.post(
            room, "bot:review-bot", {"body": "Old", "request_id": "same"}
        )
        self.store.remove_agent(room, "review-bot")
        self.store.join(room, "review-bot")
        new = self.store.discussions.post(
            room, "bot:review-bot", {"body": "New", "request_id": "same"}
        )
        self.assertNotEqual(old["id"], new["id"])

    def test_final_root_reply_does_not_wake_an_unanswerable_target(self):
        room = self.room()
        self.store.register_bot("second-bot", "Second", "dot")
        self.store.join(room, "second-bot")
        self.store.grant(room, "review-bot", 20)
        root = self.store.discussions.post(
            room,
            "user",
            {
                "body": "Question",
                "request_id": "root",
                "mentions": ["review-bot"],
                "budget": 2,
            },
        )
        self.store.discussions.post(
            room,
            "bot:review-bot",
            {
                "body": "First",
                "request_id": "one",
                "reply_to": root["id"],
            },
        )
        self.store.discussions.post(
            room,
            "bot:review-bot",
            {
                "body": "Final",
                "request_id": "two",
                "reply_to": root["id"],
                "mentions": ["second-bot"],
            },
        )
        self.assertEqual(self.store.discussions.inbox(room, "bot:second-bot", {})["messages"], [])
