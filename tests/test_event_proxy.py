"""Synthetic CONNECT security contract: no external requests or credentials."""

import io
import socket
import ssl
import threading
import unittest
from unittest.mock import MagicMock, patch

from event_delivery import CallbackTransport, ConnectHTTPSConnection


class EventProxyTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_defaults_and_explicit_proxy(self):
        self.assertEqual(CallbackTransport(["callback.example"]).deadline_seconds, 20)
        for value in (0, float("nan"), 121):
            with self.assertRaises(ValueError):
                CallbackTransport(["callback.example"], deadline_seconds=value)
        for url in ("https://proxy.example", "http://user:secret@proxy.example", "http://proxy/a"):
            with self.assertRaises(ValueError):
                CallbackTransport(["callback.example"], proxy_url=url)

    @patch.dict("os.environ", {"HTTPS_PROXY": "http://proxy.example"}, clear=True)
    def test_proxy_environment_alone_is_fail_closed(self):
        with patch("event_delivery.socket.getaddrinfo") as dns:
            with self.assertRaises(ValueError):
                CallbackTransport(["callback.example"]).post("https://callback.example", b"", {})
            dns.assert_not_called()

    def test_only_hostname_logged(self):
        with self.assertLogs("event_delivery", level="WARNING") as logs:
            with self.assertRaisesRegex(ValueError, "callback_host_not_approved"):
                CallbackTransport(["approved.example"]).validate(
                    "https://user:private@denied.example/private-path?secret=value"
                )
        self.assertIn("denied.example", "".join(logs.output))
        for secret in ("private", "secret", "value", "user"):
            self.assertNotIn(secret, "".join(logs.output))

    @patch.dict("os.environ", {}, clear=True)
    def test_connect_approved_hostname_and_tls_original_host(self):
        raw = MagicMock(spec=socket.socket)
        raw.makefile.return_value = io.BytesIO(b"HTTP/1.1 200 Connection established\r\n\r\n")
        context = MagicMock(spec=ssl.SSLContext)
        conn = ConnectHTTPSConnection(
            "callback.example",
            "callback.example",
            ("127.0.0.1", 8080),
            20,
            context,
            {},
            threading.Event(),
        )
        with patch("event_delivery.socket.create_connection", return_value=raw):
            conn.connect()
        self.assertIn(b"CONNECT callback.example:443 HTTP/1.1", raw.sendall.call_args.args[0])
        context.wrap_socket.assert_called_once_with(
            raw, server_hostname="callback.example", do_handshake_on_connect=False
        )

    @patch.dict("os.environ", {}, clear=True)
    def test_proxy_skips_target_dns_and_preserves_host_without_redirect(self):
        transport = CallbackTransport(["callback.example"], proxy_url="http://127.0.0.1:8080")
        with (
            patch("event_delivery.ConnectHTTPSConnection") as connection,
            patch("event_delivery.socket.getaddrinfo") as dns,
        ):
            connection.return_value.getresponse.return_value.status = 302
            connection.return_value.getresponse.return_value.read.return_value = b""
            self.assertEqual(transport.post("https://callback.example/path", b"", {})[0], 302)
            dns.assert_not_called()
            self.assertEqual(connection.call_args.args[1], "callback.example")
            self.assertEqual(connection.return_value.request.call_count, 1)
            self.assertEqual(
                connection.return_value.request.call_args.args[3]["Host"], "callback.example"
            )

    @patch.dict("os.environ", {}, clear=True)
    def test_connect_rejection_does_not_fallback_or_start_tls(self):
        raw = MagicMock(spec=socket.socket)
        raw.makefile.return_value = io.BytesIO(
            b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"
        )
        context = MagicMock(spec=ssl.SSLContext)
        conn = ConnectHTTPSConnection(
            "callback.example", "8.8.8.8", ("127.0.0.1", 8080), 20, context, {}, threading.Event()
        )
        with patch("event_delivery.socket.create_connection", return_value=raw) as create:
            with self.assertRaises(OSError):
                conn.connect()
        self.assertEqual(create.call_count, 1)
        context.wrap_socket.assert_not_called()
        raw.close.assert_called_once()

    @patch.dict("os.environ", {}, clear=True)
    def test_proxy_stall_is_bounded_and_socket_shutdown(self):
        transport = CallbackTransport(
            ["callback.example"], deadline_seconds=0.03, proxy_url="http://127.0.0.1:8080"
        )
        release = threading.Event()
        with (
            patch("event_delivery.ConnectHTTPSConnection") as connection,
            patch(
                "event_delivery.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]
            ),
        ):
            connection.return_value.request.side_effect = lambda *args: release.wait(1)
            try:
                with self.assertRaises(TimeoutError):
                    transport.post("https://callback.example", b"", {})
                connection.return_value.sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
            finally:
                release.set()

    @patch.dict("os.environ", {}, clear=True)
    def test_slow_tls_timeout_never_sends_late_post_direct_or_proxy(self):
        for proxy in (None, "http://127.0.0.1:8080"):
            transport = CallbackTransport(
                ["callback.example"], deadline_seconds=0.05, proxy_url=proxy
            )
            raw = MagicMock(spec=socket.socket)
            raw.makefile.return_value = io.BytesIO(b"HTTP/1.1 200 Connection established\r\n\r\n")
            tls = MagicMock(spec=ssl.SSLSocket)
            entered, release, closed = threading.Event(), threading.Event(), threading.Event()
            tls.close.side_effect = closed.set

            def handshake():
                entered.set()
                release.wait(2)

            tls.do_handshake.side_effect = handshake
            context = MagicMock(spec=ssl.SSLContext)
            context.wrap_socket.return_value = tls
            with (
                patch(
                    "event_delivery.socket.getaddrinfo",
                    return_value=[(2, 1, 6, "", ("8.8.8.8", 443))],
                ),
                patch("event_delivery.socket.create_connection", return_value=raw),
                patch("event_delivery.ssl.create_default_context", return_value=context),
            ):
                try:
                    with self.assertRaises(TimeoutError):
                        transport.post("https://callback.example/path", b"{}", {})
                    self.assertTrue(entered.is_set())
                    tls.shutdown.assert_called_once_with(socket.SHUT_RDWR)
                finally:
                    release.set()
                self.assertTrue(closed.wait(1))
                tls.sendall.assert_not_called()
                if proxy is None:
                    raw.sendall.assert_not_called()
                else:
                    self.assertTrue(
                        raw.sendall.call_args.args[0].startswith(b"CONNECT callback.example:443 ")
                    )
                context.wrap_socket.assert_called_once_with(
                    raw, server_hostname="callback.example", do_handshake_on_connect=False
                )
