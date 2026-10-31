"""Independent handoff review regressions; synthetic local messages only."""

import unittest
from unittest.mock import patch

from roundtable import Problem, Store


class HandoffSecurityTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("Security")["id"]
        self.store.add_agent(self.room, "worker")
        self.h = self.store.handoffs
        self.sequence = 0

    def tearDown(self):
        self.store.db.close()

    def create(self, parent=""):
        self.sequence += 1
        return self.h.create(
            self.room,
            "user",
            {
                "title": "Task",
                "context": "Explicit context",
                "assignments": [{"worker": "worker", "instruction": "Synthetic work"}],
                "budget": 10,
                "parent_task_id": parent,
                "request_id": f"create-{self.sequence}",
            },
        )["task_id"]

    def op(self, task, operation, actor="user", **kwargs):
        self.sequence += 1
        return self.h.operate(
            self.room,
            actor,
            operation,
            dict(task_id=task, request_id=f"op-{self.sequence}", **kwargs),
        )

    def claim(self, task):
        assignment = self.h.snapshot(self.room, "user", task)["assignments"][0]
        return self.op(
            task,
            "claim",
            "bot:worker",
            assignment_id=assignment["id"],
            expected_attempt=assignment["attempt"],
        )

    def finish(self, task, failed=False):
        claim = self.claim(task)
        self.op(
            task,
            "update",
            "bot:worker",
            assignment_id=claim["assignment_id"],
            lease=claim["lease"],
            attempt=claim["attempt"],
            kind="failed" if failed else "completed",
            body="Synthetic result",
        )
        return claim

    def test_cancelling_child_cancels_grandchild_but_not_sibling(self):
        root = self.create()
        child = self.create(root)
        grand = self.create(child)
        sibling = self.create(root)
        self.op(child, "cancel")
        self.assertEqual(self.h.snapshot(self.room, "user", grand)["task"]["status"], "cancelled")
        self.assertEqual(self.h.snapshot(self.room, "user", sibling)["task"]["status"], "running")
        with self.assertRaises(Problem):
            self.claim(grand)

    def test_failed_task_cancellation_cannot_be_retried(self):
        task = self.create()
        claim = self.finish(task, failed=True)
        self.op(task, "cancel")
        self.assertEqual(self.h.snapshot(self.room, "user", task)["task"]["status"], "cancelled")
        with self.assertRaises(Problem) as exc:
            self.op(task, "retry", assignment_id=claim["assignment_id"])
        self.assertEqual(exc.exception.status, 409)

    def test_root_cancellation_closes_failed_descendants(self):
        root = self.create()
        child = self.create(root)
        claim = self.finish(child, failed=True)
        self.op(root, "cancel")
        with self.assertRaises(Problem):
            self.op(child, "retry", assignment_id=claim["assignment_id"])

    def test_pending_inbox_survives_more_than_100_newer_completed_tasks(self):
        old = self.create()
        for _ in range(101):
            self.finish(self.create())
        self.assertIn(old, [item["task_id"] for item in self.h.inbox(self.room, "bot:worker")])

    def test_parent_deadline_rechecked_inside_create_transaction(self):
        root = self.create()
        with self.store.transaction():
            self.store.db.execute("UPDATE tasks SET deadline=0 WHERE id=?", (root,))
        # The earlier expiration sweep can become stale while waiting for the
        # create transaction. Deadline checks cannot rely only on that sweep.
        with patch.object(self.h, "expire", return_value=None):
            with self.assertRaises(Problem) as exc:
                self.create(root)
        self.assertEqual(exc.exception.status, 409)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)
        self.assertEqual(
            self.store.db.execute("SELECT used FROM tasks WHERE id=?", (root,)).fetchone()[0], 1
        )

    def test_context_budget_is_bounded_and_idempotent(self):
        task = self.create()
        for i in range(100):
            self.h.operate(
                self.room,
                "user",
                "context",
                dict(task_id=task, body="Context", request_id=f"context-{i}"),
            )
        replay = self.h.operate(
            self.room, "user", "context", dict(task_id=task, body="Context", request_id="context-0")
        )
        self.assertTrue(replay["added"])
        with self.assertRaises(Problem) as exc:
            self.op(task, "context", body="Over limit")
        self.assertEqual(exc.exception.status, 409)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM task_events WHERE task=? AND kind='context'", (task,)
            ).fetchone()[0],
            100,
        )

    def test_retry_with_exhausted_budget_keeps_failed_result(self):
        task = self.create()
        claim = self.finish(task, failed=True)
        with self.store.transaction():
            self.store.db.execute("UPDATE tasks SET budget=used WHERE id=?", (task,))
        with self.assertRaises(Problem) as exc:
            self.op(task, "retry", assignment_id=claim["assignment_id"])
        self.assertEqual(exc.exception.status, 409)
        assignment = self.h.snapshot(self.room, "user", task)["assignments"][0]
        self.assertEqual(assignment["status"], "failed")
        self.assertEqual(assignment["result"], "Synthetic result")

    def test_expired_lease_without_retry_budget_fails_instead_of_queueing(self):
        task = self.create()
        claim = self.claim(task)
        with self.store.transaction():
            self.store.db.execute("UPDATE tasks SET budget=used WHERE id=?", (task,))
            self.store.db.execute(
                "UPDATE assignments SET lease_until=0 WHERE id=?", (claim["assignment_id"],)
            )
        snapshot = self.h.snapshot(self.room, "user", task)
        self.assertEqual(snapshot["assignments"][0]["status"], "failed")
        self.assertEqual(snapshot["task"]["status"], "failed")
        self.assertEqual(self.h.inbox(self.room, "bot:worker"), [])

    def test_retry_cannot_reissue_old_epoch_assignment_after_rejoin(self):
        task = self.create()
        claim = self.finish(task, failed=True)
        self.store.remove_agent(self.room, "worker")
        self.store.add_agent(self.room, "worker")
        with self.assertRaises(Problem) as exc:
            self.op(task, "retry", assignment_id=claim["assignment_id"])
        self.assertEqual(exc.exception.status, 403)
        self.assertEqual(
            self.h.snapshot(self.room, "user", task)["assignments"][0]["status"], "failed"
        )

    def test_progress_cap_does_not_prevent_final_result(self):
        task = self.create()
        claim = self.claim(task)
        reports = 0
        for _ in range(61):
            try:
                self.op(
                    task,
                    "update",
                    "bot:worker",
                    assignment_id=claim["assignment_id"],
                    lease=claim["lease"],
                    attempt=claim["attempt"],
                    kind="progress",
                    body="Heartbeat",
                )
                reports += 1
            except Problem as exc:
                self.assertEqual(exc.status, 409)
                break
        self.assertLessEqual(reports, 60)
        self.op(
            task,
            "update",
            "bot:worker",
            assignment_id=claim["assignment_id"],
            lease=claim["lease"],
            attempt=claim["attempt"],
            kind="completed",
            body="Final result",
        )
        snapshot = self.h.snapshot(self.room, "user", task)
        self.assertEqual(snapshot["task"]["status"], "completed")
        self.assertEqual(snapshot["budget"]["used"], 1)
