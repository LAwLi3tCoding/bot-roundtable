import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from grok_adapter import GrokWebhook
from terminal_receipts import TerminalReceipts


class TerminalReceiptTests(unittest.TestCase):
    def test_exact_payload_and_shared_transport(self):
        adapter = GrokWebhook("https://approved.example/routine", "test-secret", "approved.example")
        with patch.object(adapter, "_post") as post:
            adapter.dispatch_terminal("a" * 24, "completed")
        self.assertEqual(
            json.loads(post.call_args.args[0]),
            {"kind": "task.finished", "id": "a" * 24, "status": "completed"},
        )
        with patch.object(adapter, "_post") as post:
            adapter.notify("message", "42")
        self.assertEqual(json.loads(post.call_args.args[0]), {"kind": "message", "id": "42"})

    def test_notification_body_validation(self):
        adapter = GrokWebhook("https://approved.example/routine", "test-secret", "approved.example")
        invalid = [
            ("handoff.available", "a" * 24, None),
            ("message.mentioned", "1", None),
            ("task.finished", "a" * 24, None),
            ("task.finished", "a" * 24, "running"),
            ("task.finished", "A" * 24, "completed"),
            ("task.assigned", "a" * 24, "queued"),
            ("message", "0", None),
            ("message", "-1", None),
            ("message", "a" * 24, None),
            ("message", "1", "completed"),
            ("message", 1, None),
        ]
        with patch.object(adapter, "_post") as post:
            for kind, item, status in invalid:
                with self.assertRaises(ValueError):
                    adapter.notify(kind, item, status)
        post.assert_not_called()

    def test_terminal_private_dns_never_connects(self):
        adapter = GrokWebhook("https://approved.example/routine", "test-secret", "approved.example")
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "grok_adapter.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]
            ),
            patch("grok_adapter.PinnedHTTPSConnection") as connection,
        ):
            with self.assertRaises(ValueError):
                adapter.dispatch_terminal("a" * 24, "completed")
            connection.assert_not_called()

    def test_restart_duplicate_and_status_change_never_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipts.db"
            adapter = Mock()
            ledger = TerminalReceipts(path)
            task = {"id": "a" * 24, "status": "completed", "context": "must not be sent"}
            self.assertEqual(ledger.send("room", task, adapter)["outcome"], "accepted")
            ledger.close()
            ledger = TerminalReceipts(path)
            task["status"] = "cancelled"
            self.assertEqual(ledger.send("room", task, adapter)["reason"], "already_reserved")
            adapter.dispatch_terminal.assert_called_once_with("a" * 24, "completed")
            ledger.close()

    def test_failed_send_unknown_and_crash_reservation_not_retried(self):
        ledger = TerminalReceipts(":memory:")
        adapter = Mock()
        adapter.dispatch_terminal.side_effect = RuntimeError("secret error")
        task = {"id": "a" * 24, "status": "failed"}
        self.assertEqual(ledger.send("room", task, adapter)["outcome"], "uncertain")
        self.assertEqual(ledger.send("room", task, adapter)["reason"], "already_reserved")
        adapter.dispatch_terminal.assert_called_once()
        ledger.close()

    def test_crash_after_reservation_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipts.db"
            ledger = TerminalReceipts(path)
            adapter = Mock()
            task = {"id": "b" * 24, "status": "timeout"}
            with patch("terminal_receipts.bounded_dispatch", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    ledger.send("room", task, adapter)
            ledger.close()
            restarted = TerminalReceipts(path)
            self.assertEqual(restarted.send("room", task, adapter)["reason"], "already_reserved")
            adapter.dispatch_terminal.assert_not_called()
            restarted.close()

    def test_concurrent_connections_reserve_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipts.db"
            initial = TerminalReceipts(path)
            initial.close()
            barrier = threading.Barrier(2)
            adapter = Mock()

            def send():
                ledger = TerminalReceipts(path)
                barrier.wait(timeout=5)
                try:
                    return ledger.send("room", {"id": "c" * 24, "status": "completed"}, adapter)
                finally:
                    ledger.close()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(send) for _ in range(2)]
                results = [future.result(timeout=10) for future in futures]
            self.assertEqual(sum(item["attempted"] for item in results), 1)
            adapter.dispatch_terminal.assert_called_once()

    def test_only_supported_terminal_states(self):
        ledger = TerminalReceipts(":memory:")
        adapter = Mock()
        for state in ("running", "queued", "revoked"):
            self.assertEqual(
                ledger.send("room", {"id": "a" * 24, "status": state}, adapter)["reason"],
                "task_not_terminal",
            )
        adapter.dispatch_terminal.assert_not_called()
        for index, state in enumerate(("completed", "failed", "timeout", "cancelled")):
            self.assertTrue(
                ledger.send("room", {"id": str(index) * 24, "status": state}, adapter)["attempted"]
            )
        ledger.close()
