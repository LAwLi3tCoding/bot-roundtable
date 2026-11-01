"""Local synthetic CONNECT contract. TLS is injected; no vendor network traffic."""

import socket
import socketserver
import ssl
import threading
import unittest
from unittest.mock import patch

from event_delivery import CallbackTransport
from grok_adapter import GrokWebhook
from outbound import (
    canonical_host,
    proxy_config,
    outbound_diagnostics,
    OutboundConfigurationError,
    OutboundNotSentError,
)


class FakeTLS:
    def __init__(self, sock):
        self.sock = sock

    def do_handshake(self):
        pass

    def __getattr__(self, name):
        return getattr(self.sock, name)


class ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(2)
        reader = self.request.makefile("rb")
        line = reader.readline()
        self.server.records.append(line)
        while reader.readline() not in (b"\r\n", b""):
            pass
        self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        line = reader.readline()
        if line:
            self.server.records.append(line)
            length = 0
            for line in iter(reader.readline, b"\r\n"):
                if not line:
                    return
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1])
            reader.read(length)
            self.request.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
            )
        reader.close()


class OutboundTests(unittest.TestCase):
    def test_hostname_canonicalization_and_rejections(self):
        for name, expected in [
            ("CaLlBaCk.Example.", "callback.example"),
            ("bücher.example", "xn--bcher-kva.example"),
        ]:
            self.assertEqual(canonical_host(name), expected)
        for name in [
            "127.0.0.1",
            "::1",
            "::ffff:127.0.0.1",
            "2001:2::1",
            "127.1",
            "2130706433",
            "0x7f000001",
            "0177.0.0.1",
            "localhost",
            "a.local",
            "a.LOCAL.",
            "a.internal",
            "a.home.arpa",
            "a.lan",
            "callback.example..",
            "fe80::1%en0",
            "name",
            "a..example",
            "-a.example",
        ]:
            with self.subTest(name=name), self.assertRaises(OutboundConfigurationError):
                canonical_host(name)

    @patch.dict("os.environ", {}, clear=True)
    def test_proxy_precedence_ambient_and_diagnostics(self):
        self.assertEqual(outbound_diagnostics()["mode"], "direct_public_ip_pinning")
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://ambient.invalid"}):
            self.assertEqual(outbound_diagnostics()["reason"], "explicit_outbound_proxy_required")
            with self.assertRaises(OutboundConfigurationError):
                GrokWebhook("https://callback.example/r", "test", "callback.example").preflight()
            with patch.dict(
                "os.environ",
                {
                    "ROUNDTABLE_EVENT_PROXY": "http://127.0.0.1:80",
                    "ROUNDTABLE_OUTBOUND_PROXY": "http://[::1]:81",
                },
            ):
                self.assertEqual(proxy_config(), ("::1", 81))
                self.assertEqual(outbound_diagnostics()["mode"], "trusted_proxy_dns")
        with patch.dict(
            "os.environ", {"ROUNDTABLE_OUTBOUND_PROXY": "http://user:secret@proxy.invalid"}
        ):
            result = outbound_diagnostics()
            self.assertEqual(result["reason"], "outbound_proxy_invalid")
            self.assertNotIn("secret", str(result))

    @patch.dict("os.environ", {}, clear=True)
    def test_local_connect_hostname_fake_dns_both_paths(self):
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), ProxyHandler)
        server.daemon_threads = True
        server.records = []
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        original_dns = socket.getaddrinfo
        queried = []

        def dns(host, *args, **kwargs):
            queried.append(host)
            if host == "callback.example":
                return [(2, 1, 6, "", ("198.18.0.1", 443))]
            return original_dns(host, *args, **kwargs)

        contexts = []
        real_context = ssl.create_default_context

        def context():
            ctx = real_context()
            self.assertTrue(ctx.check_hostname)
            self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
            contexts.append(ctx)

            def wrap(sock, *, server_hostname, do_handshake_on_connect):
                self.assertEqual(server_hostname, "callback.example")
                self.assertFalse(do_handshake_on_connect)
                return FakeTLS(sock)

            ctx.wrap_socket = wrap
            return ctx

        try:
            with (
                patch.dict(
                    "os.environ",
                    {"ROUNDTABLE_OUTBOUND_PROXY": f"http://127.0.0.1:{server.server_address[1]}"},
                ),
                patch("socket.getaddrinfo", side_effect=dns),
                patch("ssl.create_default_context", side_effect=context),
            ):
                self.assertEqual(
                    CallbackTransport(["CALLBACK.EXAMPLE."]).post(
                        "https://Callback.Example./event", b"{}", {}
                    )[0],
                    200,
                )
                GrokWebhook(
                    "https://Callback.Example./routine", "synthetic", "CALLBACK.EXAMPLE."
                ).dispatch_terminal("a" * 24, "completed")
            self.assertNotIn("callback.example", queried)
            self.assertEqual(
                sum(x.startswith(b"CONNECT callback.example:443 ") for x in server.records), 2
            )
            self.assertEqual(sum(x.startswith(b"POST ") for x in server.records), 2)
            self.assertEqual(len(contexts), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    @patch.dict("os.environ", {}, clear=True)
    def test_proxy_allowlist_and_certificate_failures(self):
        with self.assertRaises(ValueError):
            GrokWebhook("https://other.example/r", "test", "callback.example")
        with self.assertRaises(ValueError):
            CallbackTransport(["callback.example"]).validate("https://other.example/r")
        with (
            patch.dict("os.environ", {"ROUNDTABLE_OUTBOUND_PROXY": "http://127.0.0.1:80"}),
            patch("event_delivery.ConnectHTTPSConnection") as conn,
        ):
            conn.return_value.connect.side_effect = ssl.SSLCertVerificationError("synthetic")
            adapter = GrokWebhook("https://callback.example/r", "test", "callback.example")
            with self.assertRaises(OutboundNotSentError):
                adapter.dispatch_terminal("a" * 24, "completed")
            conn.return_value.request.assert_not_called()

    @patch.dict("os.environ", {"ROUNDTABLE_OUTBOUND_PROXY": "http://127.0.0.1:80"}, clear=True)
    def test_event_certificate_failure_is_not_ignored(self):
        with (
            patch(
                "event_delivery.ConnectHTTPSConnection.connect",
                side_effect=ssl.SSLCertVerificationError("synthetic"),
            ),
            patch("socket.getaddrinfo") as dns,
        ):
            with self.assertRaises(ValueError):
                CallbackTransport(["callback.example"]).post(
                    "https://callback.example/event", b"{}", {}
                )
            dns.assert_not_called()

    @patch.dict("os.environ", {}, clear=True)
    def test_preflight_snapshot_survives_environment_and_concurrent_dispatch_change(self):
        adapter = GrokWebhook("https://callback.example/r", "synthetic", "callback.example")
        direct = adapter.preflight()
        entered, release = threading.Event(), threading.Event()
        errors = []

        def dns(*args, **kwargs):
            entered.set()
            release.wait(2)
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        def old_dispatch():
            try:
                adapter.dispatch_terminal("a" * 24, "completed", transport=direct)
            except Exception as exc:
                errors.append(exc)

        with (
            patch("socket.getaddrinfo", side_effect=dns),
            patch("grok_adapter.PinnedHTTPSConnection") as pinned,
            patch("event_delivery.ConnectHTTPSConnection") as connect,
        ):
            pinned.return_value.getresponse.return_value.status = 200
            connect.return_value.getresponse.return_value.status = 200
            # Environment can change even before the preflighted worker starts.
            with patch.dict("os.environ", {"ROUNDTABLE_OUTBOUND_PROXY": "http://127.0.0.1:80"}):
                thread = threading.Thread(target=old_dispatch)
                thread.start()
                try:
                    self.assertTrue(entered.wait(1))
                    proxied = adapter.preflight()
                    adapter.dispatch_terminal("b" * 24, "completed", transport=proxied)
                finally:
                    release.set()
                    thread.join(2)
            self.assertFalse(errors)
            pinned.assert_called_once()
            connect.assert_called_once()
            self.assertEqual(connect.call_args.args[1], "callback.example")

    @patch.dict("os.environ", {}, clear=True)
    def test_direct_fake_ipv4_ipv6_rejected(self):
        for ip in ("198.18.0.1", "2001:2::1", "127.0.0.1"):
            with (
                patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443))]),
                patch("socket.create_connection") as connect,
            ):
                with self.assertRaises(ValueError):
                    CallbackTransport(["callback.example"]).post(
                        "https://callback.example/r", b"{}", {}
                    )
                with self.assertRaises(ValueError):
                    GrokWebhook(
                        "https://callback.example/r", "test", "callback.example"
                    ).dispatch_terminal("a" * 24, "completed")
                connect.assert_not_called()
