import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from roundtable import Problem, Store


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.rid = self.store.room("Handoffs")["id"]
        for aid in ("origin", "worker-one", "worker-two", "outsider"):
            self.store.add_agent(self.rid, aid)
        self.store.grant(self.rid, "origin", 20)
        self.store.settings(self.rid, "Handoffs", "origin")
        self.h = self.store.handoffs
        self.actor = "bot:origin"

    def tearDown(self):
        self.store.db.close()

    def create(self, **overrides):
        data = dict(
            title="Native delegation",
            context="Explicit shared context only",
            assignments=[
                dict(worker="worker-one", instruction="Research A"),
                dict(worker="worker-two", instruction="Check B"),
            ],
            budget=6,
            request_id="create",
        )
        data.update(overrides)
        return self.h.create(self.rid, self.actor, data)

    def snapshot(self, task, actor=None):
        return self.h.snapshot(self.rid, actor or self.actor, task["task_id"])

    def claim(self, task, index=0, nonce="claim"):
        a = self.snapshot(task)["assignments"][index]
        return self.h.operate(
            self.rid,
            "bot:" + a["worker"],
            "claim",
            dict(
                task_id=task["task_id"],
                assignment_id=a["id"],
                expected_attempt=a["attempt"],
                request_id=nonce,
            ),
        )

    def report(self, claim, actor="bot:worker-one", kind="completed", nonce="result"):
        return self.h.operate(
            self.rid,
            actor,
            "update",
            dict(
                task_id=claim["task_id"],
                assignment_id=claim["assignment_id"],
                lease=claim["lease"],
                attempt=claim["attempt"],
                kind=kind,
                body="Synthetic result",
                request_id=nonce,
            ),
        )

    def test_system_lifecycle_notices_never_emit_mention_wakes(self):
        cursor = self.h.event_feed(
            self.rid,
            "bot:worker-one",
            {"name": "roundtable.notification", "arguments": {}, "after": None},
        )["cursor"]
        task = self.create(assignments=[dict(worker="worker-one", instruction="Synthetic")])
        claim = self.claim(task)
        self.report(claim)
        notices = self.store.discussions.listing(self.rid)
        self.assertEqual(len(notices), 3)
        self.assertEqual({row["sender"] for row in notices}, {"system"})
        for kind in ("delegated", "claimed", "completed"):
            self.assertTrue(any(row["notice"]["kind"] == kind for row in notices))
        self.assertEqual(
            self.store.discussions.inbox(self.rid, "bot:worker-one", {})["messages"], []
        )
        events = self.h.event_feed(
            self.rid,
            "bot:worker-one",
            {"name": "roundtable.notification", "arguments": {}, "after": cursor},
        )["events"]
        self.assertFalse([e for e in events if e["data"]["kind"] == "mention"])

    def test_generic_notification_kinds_and_payloads(self):
        def feed(actor, after):
            return self.h.event_feed(
                self.rid,
                actor,
                {"name": "roundtable.notification", "arguments": {}, "after": after},
            )

        worker_cursor = feed("bot:worker-one", None)["cursor"]
        origin_cursor = feed(self.actor, None)["cursor"]
        task = self.create(assignments=[dict(worker="worker-one", instruction="Synthetic")])
        assigned = feed("bot:worker-one", worker_cursor)["events"]
        self.assertEqual(
            [e["data"] for e in assigned], [{"kind": "task.assigned", "id": task["task_id"]}]
        )
        self.assertEqual({e["name"] for e in assigned}, {"roundtable.notification"})
        self.report(self.claim(task))
        origin = [e["data"] for e in feed(self.actor, origin_cursor)["events"]]
        self.assertIn({"kind": "task.updated", "id": task["task_id"], "status": "claimed"}, origin)
        self.assertEqual(
            origin[-1], {"kind": "task.finished", "id": task["task_id"], "status": "completed"}
        )
        self.assertTrue(all(set(e) <= {"kind", "id", "status"} for e in origin))
        self.assertNotIn("Synthetic", repr(origin))
        topic = self.store.mailboxes.create(
            self.rid,
            "user",
            {"members": ["bot:origin"], "title": "Synthetic", "request_id": "topic"},
        )["id"]
        mention = self.store.mailboxes.post(
            self.rid,
            "user",
            topic,
            {"body": "Synthetic mention", "mentions": ["bot:origin"], "request_id": "m1"},
        )
        cursor = feed(self.actor, origin_cursor)["cursor"]
        self.assertEqual(feed(self.actor, cursor)["events"], [])
        page = feed(self.actor, origin_cursor)["events"]
        self.assertEqual(page[-1]["data"], {"kind": "message", "id": str(mention["id"])})
        for name, arguments in (
            ("handoff.available", {}),
            ("message.mentioned", {}),
            ("task.updated", {"task_id": task["task_id"]}),
            ("roundtable.notification", {"task_id": task["task_id"]}),
        ):
            with self.assertRaises(Problem):
                self.h.event_feed(
                    self.rid, self.actor, {"name": name, "arguments": arguments, "after": 0}
                )

    def test_lead_origin_independent_assignments_progress_and_fanin(self):
        with self.assertRaises(Problem):
            self.store.start(self.rid, "old discussion", ["worker-one"], 3, "old", actor=self.actor)
        task = self.create()
        self.assertEqual(task["coordinator"], self.actor)
        one, two = self.claim(task), self.claim(task, 1, "claim-two")
        self.assertNotEqual(one["assignment_id"], two["assignment_id"])
        self.report(one, kind="progress", nonce="p1")
        self.report(two, actor="bot:worker-two")
        self.assertEqual(self.snapshot(task)["task"]["status"], "running")
        self.report(one)
        snap = self.snapshot(task)
        self.assertEqual(snap["task"]["status"], "completed")
        self.assertEqual(len(snap["assignments"]), 2)
        self.assertNotIn(one["lease"], str(snap))
        cursor = self.h.snapshot(self.rid, self.actor, task["task_id"], snap["cursor"])
        self.assertEqual(cursor["events"], [])

    def test_history_list_is_bounded_preview_not_full_results(self):
        import json

        for index in range(30):
            task = self.create(request_id=f"large-{index}", context="c" * 4000)
            claim = self.claim(task, nonce=f"claim-{index}")
            self.h.operate(
                self.rid,
                "bot:worker-one",
                "update",
                dict(
                    task_id=task["task_id"],
                    assignment_id=claim["assignment_id"],
                    lease=claim["lease"],
                    attempt=claim["attempt"],
                    kind="completed",
                    body="r" * 4000,
                    request_id=f"report-{index}",
                    artifacts=[dict(name="output", text="a" * 2000)] * 3,
                ),
            )
            self.h.operate(
                self.rid,
                self.actor,
                "cancel",
                dict(
                    task_id=task["task_id"],
                    request_id=f"cancel-{index}",
                ),
            )
            self.store.grant(self.rid, "origin", 20)
        listing = self.h.listing(self.rid, self.actor)
        self.assertEqual(len(listing), 30)
        self.assertLess(len(json.dumps(listing).encode()), 100_000)
        self.assertEqual(len(listing[0]["task"]["context"]), 220)
        self.assertNotIn("result", listing[0]["assignments"][0])
        self.assertEqual(len(self.snapshot(task)["assignments"][0]["result"]), 4000)

    def test_idempotency_conflicts_for_create_claim_and_report(self):
        task = self.create()
        self.assertEqual(task, self.create())
        with self.assertRaises(Problem) as e:
            self.create(context="different")
        self.assertEqual(e.exception.status, 409)
        claim = self.claim(task)
        replay = dict(
            task_id=task["task_id"],
            assignment_id=claim["assignment_id"],
            expected_attempt=0,
            request_id="claim",
        )
        self.assertEqual(claim, self.h.operate(self.rid, "bot:worker-one", "claim", replay))
        first = self.report(claim)
        self.assertEqual(first, self.report(claim))
        with self.assertRaises(Problem):
            self.report(claim, kind="failed")
        self.assertEqual(
            len([e for e in self.snapshot(task)["events"] if e["kind"] == "completed"]), 1
        )

    def test_worker_permissions_context_and_cross_room(self):
        task = self.create()
        snap = self.snapshot(task, "bot:worker-one")
        self.assertEqual([a["worker"] for a in snap["assignments"]], ["worker-one"])
        self.assertNotIn("Check B", str(snap))
        for actor in ("bot:outsider",):
            with self.assertRaises(Problem):
                self.snapshot(task, actor)
        with self.assertRaises(Problem):
            self.h.snapshot(self.store.room("Other")["id"], "user", task["task_id"])
        aid = self.snapshot(task)["assignments"][1]["id"]
        with self.assertRaises(Problem):
            self.h.operate(
                self.rid,
                "bot:worker-one",
                "claim",
                dict(
                    task_id=task["task_id"],
                    assignment_id=aid,
                    expected_attempt=0,
                    request_id="steal",
                ),
            )
        with self.assertRaises(Problem):
            self.h.operate(
                self.rid,
                "bot:worker-one",
                "cancel",
                dict(task_id=task["task_id"], request_id="cancel"),
            )
        self.h.operate(
            self.rid,
            self.actor,
            "context",
            dict(
                task_id=task["task_id"],
                assignment_id=aid,
                body="Private B context",
                request_id="note",
            ),
        )
        self.assertNotIn("Private B context", str(self.snapshot(task, "bot:worker-one")))
        self.assertIn("Private B context", str(self.snapshot(task, "bot:worker-two")))
        with self.assertRaises(Problem):
            self.create(assignments=[dict(worker="origin", instruction="self")])

    def test_failure_retry_budget_and_stale_lease(self):
        task = self.create(budget=3)
        first = self.claim(task)
        self.report(first, kind="failed")
        self.h.operate(
            self.rid,
            self.actor,
            "retry",
            dict(task_id=task["task_id"], assignment_id=first["assignment_id"], request_id="retry"),
        )
        next_claim = self.claim(task, nonce="claim2")
        self.assertEqual(next_claim["attempt"], 2)
        with self.assertRaises(Problem):
            self.report(first, nonce="stale")
        self.report(next_claim, kind="failed", nonce="result2")
        with self.assertRaises(Problem):
            self.h.operate(
                self.rid,
                self.actor,
                "retry",
                dict(
                    task_id=task["task_id"],
                    assignment_id=first["assignment_id"],
                    request_id="retry2",
                ),
            )
        self.assertEqual(self.snapshot(task)["budget"]["used"], 3)

    def test_legacy_lease_schema_upgrade_preserves_active_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "legacy.db")
            legacy = Store(path)
            room = legacy.room("Legacy")["id"]
            legacy.add_agent(room, "worker")
            task = legacy.handoffs.create(
                room,
                "user",
                dict(
                    title="Migration",
                    context="Synthetic",
                    assignments=[dict(worker="worker", instruction="Read")],
                    budget=1,
                    request_id="create",
                ),
            )
            assignment = legacy.handoffs.snapshot(room, "user", task["task_id"])["assignments"][0]
            claim = legacy.handoffs.operate(
                room,
                "bot:worker",
                "claim",
                dict(
                    task_id=task["task_id"],
                    assignment_id=assignment["id"],
                    expected_attempt=0,
                    request_id="claim",
                ),
            )
            legacy.db.execute("ALTER TABLE assignments DROP COLUMN lease_seconds")
            legacy.db.commit()
            legacy.db.close()
            upgraded = Store(path)
            try:
                row = upgraded.db.execute(
                    "SELECT lease_seconds,lease_until FROM assignments WHERE id=?",
                    (assignment["id"],),
                ).fetchone()
                self.assertEqual(row["lease_seconds"], 60)
                self.assertEqual(row["lease_until"], claim["lease_until"])
                upgraded.handoffs.operate(
                    room,
                    "bot:worker",
                    "update",
                    dict(
                        task_id=task["task_id"],
                        assignment_id=assignment["id"],
                        lease=claim["lease"],
                        attempt=claim["attempt"],
                        kind="completed",
                        body="Synthetic",
                        request_id="result",
                    ),
                )
                self.assertEqual(
                    upgraded.handoffs.snapshot(room, "user", task["task_id"])["task"]["status"],
                    "completed",
                )
            finally:
                upgraded.db.close()

    def test_configurable_lease_bounds_renewal_and_deadline(self):
        import time

        task = self.create(timeout_seconds=86400)
        a = self.snapshot(task)["assignments"][0]
        data = dict(
            task_id=task["task_id"],
            assignment_id=a["id"],
            expected_attempt=0,
            request_id="custom-lease",
            lease_seconds=1800,
        )
        for invalid in (29, 1801, True, "60"):
            with self.assertRaises(Problem):
                self.h.operate(
                    self.rid, "bot:worker-one", "claim", dict(data, lease_seconds=invalid)
                )
        claim = self.h.operate(self.rid, "bot:worker-one", "claim", data)
        self.assertGreater(claim["lease_until"], time.time() + 1790)
        self.report(claim, kind="progress", nonce="renew-custom")
        row = self.store.db.execute(
            "SELECT lease_until FROM assignments WHERE id=?", (a["id"],)
        ).fetchone()
        self.assertGreater(row[0], time.time() + 1790)
        self.store.db.execute("UPDATE assignments SET lease_until=0 WHERE id=?", (a["id"],))
        self.store.db.commit()
        second = self.h.operate(
            self.rid,
            "bot:worker-one",
            "claim",
            dict(data, expected_attempt=1, request_id="reclaim-custom"),
        )
        self.assertEqual(second["attempt"], 2)
        with self.assertRaises(Problem):
            self.report(claim, nonce="stale-custom")
        short = self.create(request_id="short", timeout_seconds=30)
        b = self.snapshot(short)["assignments"][0]
        capped = self.h.operate(
            self.rid,
            "bot:worker-one",
            "claim",
            dict(data, task_id=short["task_id"], assignment_id=b["id"], request_id="capped"),
        )
        self.assertEqual(capped["lease_until"], self.snapshot(short)["task"]["deadline"])
        with self.assertRaises(Problem):
            self.create(request_id="too-long", timeout_seconds=86401)

    def test_lease_expiration_recovery_deadline_and_cancel(self):
        task = self.create()
        first = self.claim(task)
        self.store.db.execute(
            "UPDATE assignments SET lease_until=0 WHERE id=?", (first["assignment_id"],)
        )
        self.store.db.commit()
        second = self.claim(task, nonce="new-lease")
        self.assertEqual(second["attempt"], 2)
        with self.assertRaises(Problem):
            self.report(first, nonce="late")
        self.h.operate(
            self.rid, self.actor, "cancel", dict(task_id=task["task_id"], request_id="cancel")
        )
        with self.assertRaises(Problem):
            self.report(second)
        self.assertEqual(self.snapshot(task)["task"]["status"], "cancelled")
        other = self.create(request_id="deadline")
        self.store.db.execute("UPDATE tasks SET deadline=0 WHERE id=?", (other["task_id"],))
        self.store.db.commit()
        self.assertEqual(self.snapshot(other)["task"]["status"], "timeout")

    def test_simultaneous_claim_and_cancel_reply_are_serialized(self):
        task = self.create()
        a = self.snapshot(task)["assignments"][0]
        barrier = threading.Barrier(2)

        def claim(nonce):
            barrier.wait()
            try:
                return self.h.operate(
                    self.rid,
                    "bot:worker-one",
                    "claim",
                    dict(
                        task_id=task["task_id"],
                        assignment_id=a["id"],
                        expected_attempt=0,
                        request_id=nonce,
                    ),
                )
            except Problem:
                return None

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(claim, ["a", "b"]))
        winners = [r for r in results if r]
        self.assertEqual(len(winners), 1)
        barrier = threading.Barrier(2)

        def finish(cancel):
            barrier.wait()
            try:
                return (
                    self.h.operate(
                        self.rid,
                        self.actor,
                        "cancel",
                        dict(task_id=task["task_id"], request_id="cancel"),
                    )
                    if cancel
                    else self.report(winners[0])
                )
            except Problem:
                return None

        with ThreadPoolExecutor(2) as pool:
            list(pool.map(finish, [False, True]))
        self.assertEqual(self.snapshot(task)["task"]["status"], "cancelled")
        self.assertFalse(any(a["status"] == "working" for a in self.snapshot(task)["assignments"]))

    def test_revoked_membership_cannot_rejoin_old_assignments(self):
        task = self.create()
        claim = self.claim(task)
        self.store.remove_agent(self.rid, "worker-one")
        self.store.add_agent(self.rid, "worker-one")
        with self.assertRaises(Problem):
            self.snapshot(task, "bot:worker-one")
        with self.assertRaises(Problem):
            self.report(claim)
        self.store.remove_agent(self.rid, "origin")
        self.store.add_agent(self.rid, "origin")
        with self.assertRaises(Problem):
            self.snapshot(task)
        with self.assertRaises(Problem):
            self.create()

    def test_parent_depth_shared_budget_and_cancel(self):
        root = self.create(budget=6)
        child = self.create(parent_task_id=root["task_id"], request_id="child")
        grand = self.create(parent_task_id=child["task_id"], request_id="grand")
        with self.assertRaises(Problem):
            self.create(parent_task_id=grand["task_id"], request_id="deep")
        with self.assertRaises(Problem):
            self.create(parent_task_id=root["task_id"], request_id="extra")
        self.h.operate(
            self.rid, self.actor, "cancel", dict(task_id=root["task_id"], request_id="cancel")
        )
        self.assertEqual(self.snapshot(grand)["task"]["status"], "cancelled")

    def test_restart_preserves_tasks_events_and_unexpired_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "test.db")
            s = Store(path)
            rid = s.room("Persistent")["id"]
            s.add_agent(rid, "worker-one")
            task = s.handoffs.create(
                rid,
                "user",
                dict(
                    title="Restart",
                    context="Scoped",
                    assignments=[dict(worker="worker-one", instruction="one")],
                    request_id="a",
                ),
            )
            a = s.handoffs.snapshot(rid, "user", task["task_id"])["assignments"][0]
            claim = s.handoffs.operate(
                rid,
                "bot:worker-one",
                "claim",
                dict(
                    task_id=task["task_id"],
                    assignment_id=a["id"],
                    expected_attempt=0,
                    request_id="claim",
                ),
            )
            s.db.close()
            s = Store(path)
            self.assertEqual(
                s.handoffs.snapshot(rid, "user", task["task_id"])["assignments"][0]["status"],
                "working",
            )
            s.handoffs.operate(
                rid,
                "bot:worker-one",
                "update",
                dict(
                    task_id=task["task_id"],
                    assignment_id=a["id"],
                    lease=claim["lease"],
                    attempt=1,
                    kind="completed",
                    body="after restart",
                    request_id="result",
                ),
            )
            self.assertEqual(
                s.handoffs.snapshot(rid, "user", task["task_id"])["task"]["status"], "completed"
            )
            s.db.close()
