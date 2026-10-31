import unittest
import time
from unittest.mock import patch

from grok_adapter import GrokWebhook


class AddressSecurityTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("grok_adapter.PinnedHTTPSConnection")
    def test_multicast_and_reserved_never_connect(self, connection):
        adapter = GrokWebhook("https://example.com/routine", "test-key", "example.com")
        for ip in [
            "224.0.0.1",
            "ff02::1",
            "240.0.0.1",
            "169.254.169.254",
            "::1",
            "::ffff:127.0.0.1",
        ]:
            with (
                self.subTest(ip=ip),
                patch("grok_adapter.socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443))]),
            ):
                with self.assertRaises(ValueError):
                    adapter.dispatch({"deadline": time.time() + 60})
        connection.assert_not_called()

    @patch.dict("os.environ", {}, clear=True)
    @patch("grok_adapter.socket.getaddrinfo")
    def test_stale_or_invalid_job_does_not_resolve(self, dns):
        adapter = GrokWebhook("https://example.com/routine", "test-key", "example.com")
        for deadline in (0, time.time() - 1, None, True, float("nan"), float("inf")):
            with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                adapter.dispatch({"deadline": deadline})
        dns.assert_not_called()
