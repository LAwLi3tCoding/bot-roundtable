import json
import unittest
from unittest.mock import Mock, patch

from event_delivery import CallbackTransport
from mcp_events import EventError
from mcp_http import ScopedVerifier, parse_grants
import test_mcp_events as fixtures

subscription = fixtures.subscription


class AuthorizationTests(unittest.TestCase):
    def test_three_states_and_strict_200(self):
        verifier = ScopedVerifier(
            "http://127.0.0.1:12345",
            parse_grants(
                json.dumps([{"room": "a" * 24, "agent": "test-worker", "token": "s" * 40}])
            ),
        )
        grant = next(iter(verifier.grants.values()))
        good = {"authorized": True, "room": grant.room, "agent": grant.agent}
        cases = [
            (200, good, True),
            (401, {}, False),
            (403, {}, False),
            (500, {}, None),
            (503, {}, None),
            (200, {}, None),
            (200, dict(good, authorized=1), None),
            (200, dict(good, room="b" * 24), None),
        ]
        for status, body, expected in cases:
            response = Mock(status=status)
            response.read.return_value = json.dumps(body).encode()
            conn = Mock()
            conn.getresponse.return_value = response
            with patch("mcp_http.http.client.HTTPConnection", return_value=conn):
                self.assertIs(verifier.still_authorized(grant), expected)
        with patch("mcp_http.http.client.HTTPConnection") as factory:
            factory.return_value.request.side_effect = OSError("synthetic")
            self.assertIsNone(verifier.still_authorized(grant))


class AvailabilityTests(unittest.TestCase):
    setUp = fixtures.EventsFixture.setUp
    tearDown = fixtures.EventsFixture.tearDown
    create = fixtures.EventsFixture.create

    def test_unavailable_preserved_backoff_recovery_and_revoke(self):
        sid = self.broker.rpc("events/subscribe", subscription())["id"]
        self.create()
        with patch.object(self.verifier, "still_authorized", return_value=None) as check:
            self.broker.dispatch_once()
            self.broker.dispatch_once()
            self.assertEqual(check.call_count, 1)
        row = self.broker.db.execute("SELECT * FROM subscriptions WHERE id=?", (sid,)).fetchone()
        self.assertEqual(row["last_error"], "backend_unavailable")
        self.assertGreater(row["expires"], 0)
        self.assertEqual(len(self.receiver.records), 1)  # only verification
        self.broker.unavailable_until.clear()
        self.broker.dispatch_once()
        self.assertEqual(len(self.receiver.records), 2)
        with patch.object(self.verifier, "still_authorized", return_value=False):
            with self.assertLogs(level="INFO") as logs:
                self.broker.dispatch_once()
        self.assertIn("event_subscription_revoked", " ".join(logs.output))
        self.broker.dispatch_once()
        self.assertEqual(
            self.broker.db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0
        )

    def test_post_send_unavailable_does_not_repeat_success(self):
        self.broker.rpc("events/subscribe", subscription())
        self.create()
        with patch.object(self.verifier, "still_authorized", side_effect=[True, None]):
            self.broker.dispatch_once()
        self.broker.unavailable_until.clear()
        self.broker.dispatch_once()
        self.assertEqual(len(self.receiver.records), 2)
        self.assertEqual(self.broker.db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 0)

    def test_deny_all_discovery_no_dns_challenge_or_persistence(self):
        self.broker.transport = CallbackTransport([])
        self.assertEqual(len(self.broker.rpc("events/list", {})["events"]), 2)
        with (
            patch("socket.getaddrinfo", side_effect=AssertionError("no DNS")),
            patch("socket.create_connection", side_effect=AssertionError("no socket")),
        ):
            with self.assertLogs("event_delivery", level="WARNING") as logs:
                with self.assertRaises(EventError) as error:
                    self.broker.rpc("events/subscribe", subscription())
        self.assertEqual(error.exception.reason, "callback_not_allowed")
        self.assertEqual(
            self.broker.db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0
        )
        output = " ".join(logs.output)
        self.assertIn("callback.example.com", output)
        self.assertNotIn("/unique", output)
        self.assertNotIn(subscription()["delivery"]["secret"], output)

    def test_lifecycle_logs_no_subscription_secrets(self):
        params = subscription()
        with self.assertLogs(level="INFO") as logs:
            self.broker.rpc("events/subscribe", params)
            self.broker.rpc("events/subscribe", params)
            cancel = dict(params, delivery={"mode": "webhook", "url": params["delivery"]["url"]})
            self.broker.rpc("events/unsubscribe", cancel)
            self.broker.rpc("events/subscribe", params)
            self.broker.cleanup(10**12)
        output = " ".join(logs.output)
        for word in ("created", "renewed", "cancelled", "expired"):
            self.assertIn("event_subscription_" + word, output)
        for secret in (
            params["delivery"]["url"],
            params["delivery"]["secret"],
            self.current["token"],
        ):
            self.assertNotIn(secret, output)
