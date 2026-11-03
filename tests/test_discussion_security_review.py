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
