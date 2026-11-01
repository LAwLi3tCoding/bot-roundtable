import unittest

from mcp_http import OriginGate


class TunnelGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwarded_case_insensitive_override_rejected(self):
        called = []

        async def app(scope, receive, send):
            called.append(True)

        gate = OriginGate(app, ["127.0.0.1:8766"], [], "Bearer synthetic-expected")
        for header in (b"Authorization", b"aUtHoRiZaTiOn"):
            messages = []

            async def send(message):
                messages.append(message)

            await gate(
                {
                    "type": "http",
                    "headers": [
                        (b"host", b"127.0.0.1:8766"),
                        (header, b"Bearer synthetic-forwarded"),
                    ],
                },
                None,
                send,
            )
            self.assertEqual(messages[0]["status"], 403)
            self.assertIn(b"tunnel_authorization_mismatch", messages[1]["body"])
            self.assertNotIn(b"synthetic-forwarded", messages[1]["body"])
        self.assertEqual(called, [])
        await gate(
            {
                "type": "http",
                "headers": [
                    (b"host", b"127.0.0.1:8766"),
                    (b"authorization", b"Bearer synthetic-expected"),
                ],
            },
            None,
            send,
        )
        self.assertEqual(called, [True])
