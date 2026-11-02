"""One-time UI authentication security; isolated HTTP server, synthetic secrets."""

from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import threading
import unittest

from roundtable import Store, Problem
from server import make_server
from ui_sessions import UISessions


class CodeContracts(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.codes = UISessions(clock=lambda: self.now)

    def test_atomic_single_consumer_and_no_plaintext_storage(self):
        code = self.codes.issue()["code"]

        def consume(_):
            try:
                return self.codes.exchange(code)
            except Problem:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, range(2)))
        self.assertEqual(sum(x is not None for x in results), 1)
        self.assertNotIn(code, str(self.codes.codes))
        token = next(x["session_token"] for x in results if x)
        self.assertNotIn(token, str(self.codes.sessions))
        self.assertTrue(self.codes.valid(token))
        self.codes.revoke(token)
        self.assertFalse(self.codes.valid(token))

    def test_expiry_code_and_session(self):
        code = self.codes.issue()["code"]
        self.now += 60
        with self.assertRaises(Problem):
            self.codes.exchange(code)
        token = self.codes.exchange(self.codes.issue()["code"])["session_token"]
        self.now += 3600
        self.assertFalse(self.codes.valid(token))

    def test_bounded_codes_failures_and_recovery(self):
        for _ in range(16):
            self.codes.issue()
        with self.assertRaises(Problem) as caught:
            self.codes.issue()
        self.assertEqual(caught.exception.status, 429)
        self.now += 60
        code = self.codes.issue()["code"]
        for _ in range(20):
            with self.assertRaises(Problem):
                self.codes.exchange("invalid")
        with self.assertRaises(Problem) as caught:
            self.codes.exchange(code)
        self.assertEqual(caught.exception.status, 429)
        self.now += 60
        self.assertTrue(self.codes.exchange(self.codes.issue()["code"]))

    def test_full_sessions_do_not_consume_code(self):
        code = self.codes.issue()["code"]
        self.codes.sessions = {str(i): 200 for i in range(32)}
        with self.assertRaises(Problem):
            self.codes.exchange(code)
        self.codes.sessions.clear()
        self.assertTrue(self.codes.exchange(code))

    def test_exact_peer_host_origin_no_proxy_trust(self):
        for peer, host, origin in [
            ("127.0.0.2", "127.0.0.1:1234", "http://127.0.0.1:1234"),
            ("::1", "127.0.0.1:1234", "http://127.0.0.1:1234"),
            ("192.0.2.1", "127.0.0.1:1234", "http://127.0.0.1:1234"),
            ("127.0.0.1", "localhost:1234", "http://localhost:1234"),
            ("127.0.0.1", "127.0.0.1:1235", "http://127.0.0.1:1234"),
            ("127.0.0.1", "127.0.0.1:1234", None),
            ("127.0.0.1", "127.0.0.1:1234", "null"),
        ]:
            with self.assertRaises(Problem):
                self.codes.boundary(peer, host, origin, 1234, exchange=True)


class LoginHTTP(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.admin = "synthetic-admin-" + "x" * 40
        self.server = make_server(self.store, self.admin, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.db.close()

    def call(self, path, token="", body=None, headers=None, method="POST"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            values = {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
                "Origin": self.origin,
            }
            values.update(headers or {})
            if values.get("Origin") is None:
                values.pop("Origin")
            conn.request(method, path, json.dumps(body or {}) if method == "POST" else None, values)
            result = conn.getresponse()
            return result.status, json.loads(result.read()), dict(result.getheaders())
        finally:
            conn.close()

    def test_authenticated_issuance_and_restricted_session(self):
        self.assertEqual(self.call("/api/ui-login/issue")[0], 403)
        status, issued, headers = self.call(
            "/api/ui-login/issue", self.admin, headers={"Origin": None}
        )
        self.assertEqual(status, 201)
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, session, _ = self.call("/api/ui-login/exchange", body={"code": issued["code"]})
        self.assertEqual(status, 200)
        token = session["session_token"]
        self.assertNotEqual(token, self.admin)
        self.assertNotIn(self.admin, json.dumps(session))
        self.assertEqual(self.call("/api/rooms", token, method="GET")[0], 200)
        self.assertEqual(self.call("/api/bots", token, body={"id": "bad"})[0], 403)
        self.assertEqual(self.call("/api/ui-login/issue", token)[0], 403)
        self.assertEqual(self.call("/api/ui-login/exchange", body={"code": issued["code"]})[0], 403)
        self.call("/api/ui-login/revoke", token)
        self.assertEqual(self.call("/api/rooms", token, method="GET")[0], 403)

    def test_missing_foreign_origin_host_and_forwarding_rejected(self):
        issued = self.call("/api/ui-login/issue", self.admin)[1]["code"]
        for headers in (
            {"Origin": None},
            {"Origin": "http://example.com"},
            {"Host": f"localhost:{self.server.server_port}"},
            {"X-Forwarded-For": "127.0.0.1"},
            {"Forwarded": "for=127.0.0.1"},
        ):
            self.assertEqual(
                self.call("/api/ui-login/exchange", body={"code": issued}, headers=headers)[0], 403
            )
        self.assertEqual(self.call("/api/ui-login/exchange", body={"code": issued})[0], 200)

    def test_http_expiry_and_large_request(self):
        codes = getattr(self.server, "ui_sessions")
        now = [100.0]
        codes.clock = lambda: now[0]
        code = self.call("/api/ui-login/issue", self.admin)[1]["code"]
        now[0] = 160
        self.assertEqual(self.call("/api/ui-login/exchange", body={"code": code})[0], 403)
        self.assertEqual(self.call("/api/ui-login/exchange", body={"code": "x" * 33000})[0], 413)


if __name__ == "__main__":
    unittest.main()
