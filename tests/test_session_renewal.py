"""Synthetic clock regression tests; no native credentials or services."""

import unittest
from ui_sessions import UISessions
from roundtable import Problem


class Renewal(unittest.TestCase):
    def test_renew_expire_revoke(self):
        now = [0]
        sessions = UISessions(clock=lambda: now[0], session_seconds=10)
        token = sessions.exchange(sessions.issue()["code"])["session_token"]
        now[0] = 9
        sessions.renew(token)
        now[0] = 11
        self.assertTrue(sessions.valid(token))
        sessions.revoke(token)
        with self.assertRaises(Problem):
            sessions.renew(token)
        other = sessions.exchange(sessions.issue()["code"])["session_token"]
        now[0] = 22
        with self.assertRaises(Problem):
            sessions.renew(other)

    def test_boundary_rejects_remote_missing_origin_and_wrong_port(self):
        for peer, host, origin in [
            ("192.0.2.1", "127.0.0.1:1234", "http://127.0.0.1:1234"),
            ("127.0.0.1", "remote.invalid:1234", "http://127.0.0.1:1234"),
            ("127.0.0.1", "127.0.0.1:1235", "http://127.0.0.1:1234"),
            ("127.0.0.1", "127.0.0.1:1234", None),
            ("127.0.0.1", "127.0.0.1:1234", "http://remote.invalid"),
        ]:
            with self.assertRaises(Problem):
                UISessions.boundary(peer, host, origin, 1234, exchange=True)
