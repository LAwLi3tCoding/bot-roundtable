import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from roundtable import Store
from terminal_receipts import TerminalWorker, TerminalReceipts, configured_worker


class TerminalWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = Store(str(self.path / "source.db"))
        self.room = self.store.room("Synthetic receipts")["id"]
        for aid in ("origin", "other", "worker"):
            self.store.add_agent(self.room, aid)
            self.store.grant(self.room, aid, 20)
        self.adapter = Mock()
        self.workers = []
        self.sequence = 0

    def tearDown(self):
        for worker in self.workers:
            worker.stop()
        self.store.db.close()
        self.temp.cleanup()

    def start(self):
        worker = TerminalWorker(
            self.path / "source.db",
            self.path / "ledger.db",
            self.room,
            "origin",
            self.adapter,
            interval=0.01,
        )
        worker.start()
        self.workers.append(worker)
        return worker

    def test_legacy_schema_continues_terminal_delivery(self):
        del self.store.discussions
        self.store.db.execute("DROP TABLE discussion_mentions")
        self.store.db.execute("DROP TABLE discussion_messages")
        self.store.db.commit()
        worker = self.start()
        tid = self.task()
        self.finish(tid)
        self.until(lambda: self.adapter.dispatch_terminal.call_count == 1)
        self.assertFalse(worker.failed)

    def test_mentions_recheck_membership_after_blocked_delivery(self):
        entered, release = threading.Event(), threading.Event()

        def deliver(*args, **kwargs):
            entered.set()
            release.wait(2)

        self.adapter.dispatch_mention.side_effect = deliver
        self.start()
        with self.store.transaction():
            for index in range(2):
                self.store.discussions.post(
                    self.room,
                    "user",
                    {
                        "body": "Synthetic mention",
                        "mentions": ["origin"],
                        "request_id": "revoke-test-" + str(index),
                    },
                )
        self.assertTrue(entered.wait(2))
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE agents SET token='revoked' WHERE room=? AND id='origin'", (self.room,)
            )
        release.set()
        time.sleep(0.1)
        self.assertEqual(self.adapter.dispatch_mention.call_count, 1)

    def test_mention_delivery_and_restart_deduplication(self):
        worker = self.start()
        message = self.store.discussions.post(
            self.room,
            "user",
            {"body": "Synthetic mention", "mentions": ["origin"], "request_id": "mention-test"},
        )
        self.until(lambda: self.adapter.dispatch_mention.call_count == 1)
        self.assertEqual(self.adapter.dispatch_mention.call_args.args, (message["id"],))
        worker.stop()
        self.start()
        time.sleep(0.05)
        self.assertEqual(self.adapter.dispatch_mention.call_count, 1)

    def task(self, origin="origin"):
        self.sequence += 1
        return self.store.handoffs.create(
            self.room,
            "bot:" + origin,
            {
                "title": "Synthetic receipt",
                "context": "Test only",
                "budget": 1,
                "assignments": [{"worker": "worker", "instruction": "No external work"}],
                "request_id": str(self.sequence),
            },
        )["task_id"]

    def finish(self, tid):
        # Commit the same terminal event used by the task state machine.
        with self.store.transaction():
            self.store.db.execute("UPDATE tasks SET status='completed' WHERE id=?", (tid,))
            self.store.handoffs.event(tid, "", "system", "task_completed", "")

    def until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(condition())

    def drained(self, worker):
        # Give polling a bounded interval to consume skipped events.
        time.sleep(0.1)
        self.assertFalse(worker.failed)

    def test_configuration_backoff_keeps_cursor_then_recovers_without_replay(self):
        from grok_adapter import GrokWebhook
        from outbound import OutboundConfigurationError
        import sqlite3

        self.adapter = GrokWebhook(
            "https://approved.example/routine", "synthetic", "approved.example"
        )
        permitted = threading.Event()

        def preflight():
            if not permitted.is_set():
                raise OutboundConfigurationError("explicit_proxy_required")

        with (
            patch.object(self.adapter, "preflight", side_effect=preflight),
            patch.object(self.adapter, "dispatch_terminal") as dispatch,
        ):
            worker = self.start()
            tid = self.task()
            self.finish(tid)
            self.until(lambda: worker.status()["state"] == "backoff")
            with sqlite3.connect(self.path / "ledger.db") as ledger:
                self.assertEqual(
                    ledger.execute("SELECT COUNT(*) FROM terminal_delivery").fetchone()[0], 0
                )
            permitted.set()
            self.until(lambda: dispatch.call_count == 1)
            worker.stop()
            again = self.start()
            self.drained(again)
            self.assertEqual(dispatch.call_count, 1)

    def test_automatic_terminal_no_backlog_scope_and_restart_dedup(self):
        old = self.task()
        self.finish(old)
        running = self.task()
        worker = self.start()
        self.finish(self.task("other"))
        self.finish(running)
        self.until(lambda: self.adapter.dispatch_terminal.call_count == 1)
        self.adapter.dispatch_terminal.assert_called_once_with(running, "completed")
        self.drained(worker)
        worker.stop()
        self.start()
        self.drained(worker)
        self.adapter.dispatch_terminal.assert_called_once()

    def test_server_tick_automatically_expires_without_polling_or_demo(self):
        from server import run_ticks

        tid = self.task()
        self.start()
        with self.store.transaction():
            self.store.db.execute("UPDATE tasks SET deadline=? WHERE id=?", (time.time() - 1, tid))
        stop = threading.Event()
        thread = threading.Thread(target=run_ticks, args=(self.store, stop, 0.01))
        thread.start()
        try:
            self.until(lambda: self.adapter.dispatch_terminal.call_count == 1)
            self.adapter.dispatch_terminal.assert_called_once_with(tid, "timeout")
        finally:
            stop.set()
            thread.join(2)

    def test_revoked_epoch_skips_receipt(self):
        tid = self.task()
        worker = self.start()
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE agents SET token='replacement-epoch' WHERE room=? AND id='origin'",
                (self.room,),
            )
        self.finish(tid)
        self.drained(worker)
        self.adapter.dispatch_terminal.assert_not_called()

    def test_blocked_network_holds_no_store_lock_and_stop_is_bounded(self):
        entered, release = threading.Event(), threading.Event()

        def block(*args):
            entered.set()
            release.wait(5)

        self.adapter.dispatch_terminal.side_effect = block
        worker = self.start()
        try:
            self.finish(self.task())
            self.assertTrue(entered.wait(2))
            progress = threading.Event()

            def update():
                with self.store.transaction():
                    self.store.db.execute("SELECT COUNT(*) FROM tasks").fetchone()
                progress.set()

            thread = threading.Thread(target=update)
            thread.start()
            self.assertTrue(progress.wait(1))
            thread.join()
            before = time.monotonic()
            worker.stop()
            self.assertLess(time.monotonic() - before, 1.5)
        finally:
            release.set()
            worker.thread.join(2)

    def test_failure_is_not_retried(self):
        self.adapter.dispatch_terminal.side_effect = RuntimeError("synthetic")
        worker = self.start()
        self.finish(self.task())
        self.until(lambda: self.adapter.dispatch_terminal.call_count == 1)
        self.drained(worker)
        worker.stop()
        self.start()
        self.drained(worker)
        self.adapter.dispatch_terminal.assert_called_once()

    def test_dispatch_total_timeout_consumes_reservation(self):
        release = threading.Event()
        self.adapter.dispatch_terminal.side_effect = lambda *args: release.wait(3)
        ledger = TerminalReceipts(":memory:", delivery_timeout=0.03)
        try:
            before = time.monotonic()
            result = ledger.send("scope", {"id": "d" * 24, "status": "completed"}, self.adapter)
            self.assertLess(time.monotonic() - before, 0.5)
            self.assertEqual(result["outcome"], "uncertain")
            self.assertEqual(
                ledger.send("scope", {"id": "d" * 24, "status": "completed"}, self.adapter)[
                    "reason"
                ],
                "already_reserved",
            )
        finally:
            release.set()
            ledger.close()

    def test_stalled_dispatch_capacity_does_not_spawn_unbounded_threads(self):
        from terminal_receipts import bounded_dispatch

        release = threading.Event()
        self.adapter.dispatch_terminal.side_effect = lambda *args: release.wait(3)
        try:
            with patch("terminal_receipts._DELIVERY_SLOTS", threading.BoundedSemaphore(1)):
                with self.assertRaises(TimeoutError):
                    bounded_dispatch(self.adapter, "a" * 24, "completed", timeout=0.02)
                for _ in range(5):
                    with self.assertRaises(TimeoutError):
                        bounded_dispatch(self.adapter, "b" * 24, "completed", timeout=0.02)
                self.adapter.dispatch_terminal.assert_called_once()
                release.set()
                time.sleep(0.03)
        finally:
            release.set()

    def test_stop_during_dns_prevents_late_connection(self):
        from grok_adapter import GrokWebhook

        entered, release, returned = threading.Event(), threading.Event(), threading.Event()

        def dns(*args, **kwargs):
            entered.set()
            release.wait(3)
            returned.set()
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        self.adapter = GrokWebhook(
            "https://approved.example/routine", "synthetic", "approved.example"
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("grok_adapter.socket.getaddrinfo", side_effect=dns),
            patch("event_delivery.DirectHTTPSConnection") as connection,
        ):
            worker = self.start()
            try:
                self.finish(self.task())
                self.assertTrue(entered.wait(2))
                worker.stop()
                release.set()
                self.assertTrue(returned.wait(1))
                time.sleep(0.05)
                connection.assert_not_called()
            finally:
                release.set()

    def test_deadline_during_dns_prevents_late_connection(self):
        from grok_adapter import GrokWebhook
        from terminal_receipts import bounded_dispatch

        release, returned = threading.Event(), threading.Event()

        def dns(*args, **kwargs):
            release.wait(2)
            returned.set()
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        adapter = GrokWebhook("https://approved.example/routine", "synthetic", "approved.example")
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("grok_adapter.socket.getaddrinfo", side_effect=dns),
            patch("event_delivery.DirectHTTPSConnection") as connection,
        ):
            try:
                with self.assertRaises(TimeoutError):
                    bounded_dispatch(adapter, "a" * 24, "completed", timeout=0.02)
                release.set()
                self.assertTrue(returned.wait(1))
                time.sleep(0.05)
                connection.assert_not_called()
            finally:
                release.set()

    def test_scope_rechecked_after_previous_blocked_send(self):
        entered, release = threading.Event(), threading.Event()

        def block(*args):
            entered.set()
            release.wait(3)

        self.adapter.dispatch_terminal.side_effect = block
        worker = self.start()
        first, second = self.task(), self.task()
        # Both events become visible together; second must not rely on batch snapshot.
        with self.store.transaction():
            for tid in (first, second):
                self.store.db.execute("UPDATE tasks SET status='completed' WHERE id=?", (tid,))
                self.store.handoffs.event(tid, "", "system", "task_completed", "")
        try:
            self.assertTrue(entered.wait(2))
            with self.store.transaction():
                self.store.db.execute(
                    "UPDATE agents SET token='new-epoch' WHERE room=? AND id='origin'", (self.room,)
                )
            release.set()
            self.drained(worker)
            self.adapter.dispatch_terminal.assert_called_once_with(first, "completed")
        finally:
            release.set()

    def test_disabled_has_no_worker_or_secret_access(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("terminal_receipts.GrokWebhook") as adapter,
        ):
            self.assertIsNone(configured_worker("unused.db"))
            adapter.assert_not_called()
