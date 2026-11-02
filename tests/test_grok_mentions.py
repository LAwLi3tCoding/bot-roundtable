import unittest
from unittest.mock import Mock
from terminal_receipts import TerminalReceipts
from grok_adapter import GrokWebhook


class GrokMentions(unittest.TestCase):
    def test_durable_reservation_and_hint_only(self):
        adapter = Mock(spec=GrokWebhook)
        ledger = TerminalReceipts(":memory:")
        try:
            first = ledger.send_mention("synthetic", 12, adapter)
            second = ledger.send_mention("synthetic", 12, adapter)
            self.assertTrue(first["attempted"])
            self.assertFalse(second["attempted"])
            adapter.notify.assert_called_once()
            self.assertEqual(adapter.notify.call_args.args, ("message", "12"))
        finally:
            ledger.close()

    def test_uncertain_is_not_replayed(self):
        adapter = Mock(spec=GrokWebhook)
        adapter.notify.side_effect = TimeoutError()
        ledger = TerminalReceipts(":memory:")
        try:
            self.assertEqual(ledger.send_mention("synthetic", 13, adapter)["outcome"], "uncertain")
            self.assertFalse(ledger.send_mention("synthetic", 13, adapter)["attempted"])
            adapter.notify.assert_called_once()
        finally:
            ledger.close()
