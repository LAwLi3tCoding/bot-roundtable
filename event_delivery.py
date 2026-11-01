"""Signed MCP Events callback transport. Default-deny hosts; never follows redirects."""

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import re
import os
import socket
import ssl
import time
import threading
from urllib.parse import urlsplit
from typing import Any

from grok_adapter import PinnedHTTPSConnection
from outbound import canonical_host, proxy_config, OutboundConfigurationError


def signing_key(secret):
    if not isinstance(secret, str) or not secret.startswith("whsec_"):
        raise ValueError("Invalid signing secret")
    try:
        key = base64.b64decode(secret[6:], validate=True)
    except Exception:
        raise ValueError("Invalid signing secret") from None
    if not 24 <= len(key) <= 64:
        raise ValueError("Invalid signing secret")
    return key


def signed_headers(secret, subscription, event_id, body, previous="", now=None):
    stamp = str(int(time.time() if now is None else now))
    message = event_id.encode() + b"." + stamp.encode() + b"." + body
    signatures = [
        "v1,"
        + base64.b64encode(hmac.new(signing_key(s), message, hashlib.sha256).digest()).decode()
        for s in (secret, previous)
        if s
    ]
    return {
        "Content-Type": "application/json",
        "webhook-id": event_id,
        "webhook-timestamp": stamp,
        "webhook-signature": " ".join(signatures),
        "X-MCP-Subscription-Id": subscription,
    }


class DirectHTTPSConnection(PinnedHTTPSConnection):
    """Track TCP and TLS sockets and enforce one monotonic callback deadline."""

    def __init__(self, host, target_ip, timeout, context, state, cancelled):
        super().__init__(host, timeout=timeout, context=context)
        self.address = (target_ip, 443)
        self.tls_context = context
        self.transport_state = state
        self.cancelled = cancelled
        self.deadline = state.get("deadline", time.monotonic() + timeout)
        self.via_proxy = False

    def checkpoint(self):
        remaining = self.deadline - time.monotonic()
        if self.cancelled.is_set() or remaining <= 0:
            self.close()
            raise TimeoutError("Callback deadline exceeded")
        if self.sock is not None:
            self.sock.settimeout(remaining)
        return remaining

    def connect(self):
        self.sock = socket.create_connection(self.address, self.checkpoint())
        self.transport_state["socket"] = self.sock
        self.checkpoint()
        if self.via_proxy:
            self._tunnel()  # type: ignore[attr-defined]
        self.checkpoint()
        # Expose the SSL socket before the blocking handshake so cancellation
        # can interrupt it. TLS authenticates the original host, never the IP.
        self.sock = self.tls_context.wrap_socket(
            self.sock, server_hostname=self.host, do_handshake_on_connect=False
        )
        self.transport_state["socket"] = self.sock
        self.checkpoint()
        self.sock.do_handshake()
        self.checkpoint()

    def send(self, data):
        self.checkpoint()
        if self.sock is None:
            self.connect()
        self.checkpoint()
        super().send(data)


class ConnectHTTPSConnection(DirectHTTPSConnection):
    """Explicit trusted proxy resolves the approved hostname; TLS checks that name."""

    def __init__(self, host, target_ip, proxy, timeout, context, state, cancelled):
        super().__init__(host, target_ip, timeout, context, state, cancelled)
        self.address = proxy
        self.via_proxy = True
        authority = f"[{target_ip}]:443" if ":" in target_ip else f"{target_ip}:443"
        self.set_tunnel(target_ip, 443, headers={"Host": authority})


class CallbackTransport:
    def __init__(self, allowed_hosts, deadline_seconds=None, proxy_url=None):
        self.deadline_seconds = float(
            os.environ.get("ROUNDTABLE_EVENT_TIMEOUT", "20")
            if deadline_seconds is None
            else deadline_seconds
        )
        if not math.isfinite(self.deadline_seconds) or not 0.01 <= self.deadline_seconds <= 120:
            raise ValueError("Callback timeout must be 0.01–120 seconds")
        self.proxy = proxy_config(proxy_url)
        self.slots = threading.BoundedSemaphore(4)
        self.allowed_hosts = {canonical_host(host) for host in allowed_hosts}
        if not self.allowed_hosts:
            raise ValueError("Explicit callback host allowlist required")

    def validate(self, url):
        if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 32 for c in url):
            raise ValueError("Invalid callback URL")
        p = urlsplit(url)
        try:
            host = canonical_host(p.hostname)
        except OutboundConfigurationError:
            host = ""
        if (
            p.scheme != "https"
            or host not in self.allowed_hosts
            or p.username
            or p.password
            or p.port not in (None, 443)
            or p.fragment
        ):
            host = p.hostname or "<missing>"
            safe_host = host if re.fullmatch(r"[a-zA-Z0-9.-]{1,253}", host) else "<invalid>"
            logging.getLogger(__name__).warning("callback_host_not_approved host=%s", safe_host)
            raise ValueError("callback_host_not_approved")
        return p._replace(netloc=host)

    def post(self, url, body, headers):
        # The deadline covers DNS, TLS, headers and a trickling body, not just idle reads.
        # Uninterruptible DNS retains its slot until it finishes: bounded, fail closed.
        if not self.slots.acquire(blocking=False):
            raise TimeoutError("Callback capacity exhausted")
        done, cancelled = threading.Event(), threading.Event()
        result = []
        state: dict[str, Any] = {"deadline": time.monotonic() + self.deadline_seconds}

        def work():
            try:
                result.append(self._post(url, body, headers, cancelled, state))
            except Exception:
                result.append(None)
            finally:
                self.slots.release()
                done.set()

        threading.Thread(target=work, daemon=True).start()
        if not done.wait(self.deadline_seconds):
            cancelled.set()
            conn = state.get("connection")
            sock = state.get("socket") or getattr(conn, "sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            raise TimeoutError("Callback deadline exceeded")
        if not result or result[0] is None:
            raise ValueError("Callback transport failed")
        return result[0]

    def _post(self, url, body, headers, cancelled, state):
        p = self.validate(url)
        if len(body) > 262144:
            raise ValueError("Event too large")
        ips = []
        if not self.proxy:
            ips = [
                str(r[4][0]) for r in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
            ]
            if not ips or any(
                not ip.is_global or ip.is_multicast or ip.is_reserved
                for ip in map(ipaddress.ip_address, ips)
            ):
                raise ValueError("Non-public callback address")
        if cancelled.is_set():
            raise TimeoutError("Callback deadline exceeded")
        remaining = state["deadline"] - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Callback deadline exceeded")
        conn: PinnedHTTPSConnection
        if self.proxy:
            conn = ConnectHTTPSConnection(
                p.hostname,
                p.hostname,
                self.proxy,
                remaining,
                ssl.create_default_context(),
                state,
                cancelled,
            )
        else:
            conn = DirectHTTPSConnection(
                p.hostname, ips[0], remaining, ssl.create_default_context(), state, cancelled
            )
        state["connection"] = conn
        try:
            if cancelled.is_set():
                raise TimeoutError("Callback deadline exceeded")
            conn.request(
                "POST",
                (p.path or "/") + ("?" + p.query if p.query else ""),
                body,
                {**{k: v for k, v in headers.items() if k.lower() != "host"}, "Host": p.hostname},
            )
            state["socket"] = conn.sock
            response = conn.getresponse()
            raw = response.read(4097)
            # Callers classify status only. Never reflect response body or destination.
            if len(raw) > 4096:
                raw = b""
            return response.status, raw
        finally:
            conn.close()


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
