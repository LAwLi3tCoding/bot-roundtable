import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from connections import capabilities
from grok_adapter import GrokWebhook
from outbound import OutboundConfig, OutboundConfigurationError, OutboundNotSentError
from terminal_receipts import TerminalReceipts, TerminalWorker, private_ledger


class WorkerRecoveryTests(unittest.TestCase):
    def test_preflight_snapshot_reaches_dispatch_without_rereading_environment(self):
        adapter = GrokWebhook("https://approved.example/routine", "synthetic", "approved.example")
        ledger = TerminalReceipts(":memory:")
        config = OutboundConfig(("127.0.0.1", 12345))
        with (
            patch.object(adapter, "preflight", return_value=config) as preflight,
            patch.object(adapter, "dispatch_terminal") as dispatch,
        ):
            result = ledger.send("scope", {"id": "c" * 24, "status": "completed"}, adapter)
            self.assertEqual(result["outcome"], "accepted")
            preflight.assert_called_once()
            self.assertIs(dispatch.call_args.kwargs["transport"], config)
        ledger.close()

    def test_preflight_does_not_consume_reservation(self):
        adapter = GrokWebhook("https://approved.example/routine", "synthetic", "approved.example")
        ledger = TerminalReceipts(":memory:")
        with patch.object(
            adapter, "preflight", side_effect=OutboundConfigurationError("explicit_proxy_required")
        ):
            result = ledger.send("scope", {"id": "a" * 24, "status": "completed"}, adapter)
        self.assertEqual(result["outcome"], "definitely_not_sent")
        self.assertEqual(
            ledger.db.execute("SELECT COUNT(*) FROM terminal_delivery").fetchone()[0], 0
        )
        ledger.close()

    def test_definite_network_failure_remains_reserved(self):
        adapter = GrokWebhook("https://approved.example/routine", "synthetic", "approved.example")
        ledger = TerminalReceipts(":memory:")
        with (
            patch.object(adapter, "preflight"),
            patch(
                "terminal_receipts.bounded_dispatch", side_effect=OutboundNotSentError("not_sent")
            ),
        ):
            result = ledger.send("scope", {"id": "b" * 24, "status": "completed"}, adapter)
            self.assertTrue(result["attempted"])
            self.assertEqual(result["outcome"], "definitely_not_sent")
            self.assertEqual(
                ledger.send("scope", {"id": "b" * 24, "status": "completed"}, adapter)["reason"],
                "already_reserved",
            )
        ledger.close()

    def test_recovery_status_and_stop(self):
        worker = TerminalWorker("unused", "unused", "a" * 24, "origin", object())
        running = threading.Event()
        calls = []

        def session():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("secret raw detail")
            worker.health = {"state": "running", "reason": "", "retry_seconds": 0}
            running.set()
            worker.stop_event.wait(2)

        with patch.object(worker, "_session", side_effect=session):
            worker.start()
            status = capabilities(worker)["terminal_worker"]
            self.assertEqual(status["state"], "backoff")
            self.assertNotIn("secret", str(status))
            self.assertTrue(running.wait(2))
            self.assertEqual(worker.status()["state"], "running")
            start = time.monotonic()
            worker.stop()
            self.assertLess(time.monotonic() - start, 1)
            self.assertEqual(worker.status()["state"], "stopped")
            self.assertEqual(len(calls), 2)

    def test_private_storage_without_umask_mutation_or_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "nested" / "receipts.db"
            with patch("terminal_receipts.os.umask", side_effect=AssertionError("global umask")):
                private_ledger(target)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
            target.write_bytes(b"preserve")
            os.chmod(target, 0o400)
            private_ledger(target)
            self.assertEqual(target.read_bytes(), b"preserve")
            self.assertEqual(target.stat().st_mode & 0o777, 0o400)
