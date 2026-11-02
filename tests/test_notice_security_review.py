"""Independent checks of structured notices and expiring activity evidence."""

import json
import unittest
from unittest.mock import patch
from roundtable import Store


class NoticeSecurityReview(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.addCleanup(self.store.db.close)
        self.room = self.store.room("Synthetic")["id"]
        self.store.add_agent(self.room, "worker")
        self.h = self.store.handoffs

    def test_progress_is_bounded_and_never_copies_lease_or_artifacts(self):
        task = self.h.create(
            self.room,
            "user",
            {
                "title": "Synthetic task",
                "context": "Context",
                "budget": 10,
                "request_id": "create",
                "assignments": [{"worker": "worker", "instruction": "Work"}],
            },
        )
        assignment = self.h.snapshot(self.room, "user", task["task_id"])["assignments"][0]
        claim = self.h.operate(
            self.room,
            "bot:worker",
            "claim",
            {
                "task_id": task["task_id"],
                "assignment_id": assignment["id"],
                "expected_attempt": assignment["attempt"],
                "request_id": "claim",
            },
        )
        with patch("discussions.time.time", return_value=1000000000):
            for index in range(3):
                payload = {
                    "task_id": claim["task_id"],
                    "assignment_id": claim["assignment_id"],
                    "lease": claim["lease"],
                    "attempt": claim["attempt"],
                    "kind": "progress",
                    "body": "Safe progress",
                    "request_id": str(index),
                    "actor": "user",
                }
                self.h.operate(self.room, "bot:worker", "update", payload)
                self.h.operate(self.room, "bot:worker", "update", payload)
        notices = self.store.discussions.listing(self.room)
        progress = [row for row in notices if row["notice"]["kind"] == "progress"]
        self.assertEqual(len(progress), 1)
        self.assertEqual(progress[0]["notice"]["actor"], "bot:worker")
        self.assertNotIn(claim["lease"], json.dumps(notices))
        self.assertNotIn("Safe progress", json.dumps(notices))
        self.assertTrue(all(row["body"] == "" for row in notices))
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM discussion_mentions").fetchone()[0], 0
        )

    def test_activity_expires_and_new_epoch_is_unknown(self):
        with patch("connections.time.time", return_value=1000):
            self.store.connections.probe(self.room, "worker", "synthetic-probe-nonce")
        with patch("connections.time.time", return_value=1121):
            status = self.store.connections.status(self.room)[0]
        self.assertEqual(status["protocol_state"], "stale")
        self.assertFalse(status["vendor_account_verified"])
        self.store.remove_agent(self.room, "worker")
        self.store.add_agent(self.room, "worker")
        self.assertEqual(self.store.connections.status(self.room)[0]["protocol_state"], "unknown")
