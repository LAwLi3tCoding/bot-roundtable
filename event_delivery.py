"""Signed MCP Events callback transport. Default-deny hosts; never follows redirects."""

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import ssl
import time
from urllib.parse import urlsplit

from grok_adapter import PinnedHTTPSConnection


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


class CallbackTransport:
    def __init__(self, allowed_hosts):
        self.allowed_hosts = set(allowed_hosts)
        if not self.allowed_hosts or any(
            "*" in h or "/" in h or ":" in h for h in self.allowed_hosts
        ):
            raise ValueError("Explicit callback host allowlist required")

    def validate(self, url):
        if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 32 for c in url):
            raise ValueError("Invalid callback URL")
        p = urlsplit(url)
        if (
            p.scheme != "https"
            or p.hostname not in self.allowed_hosts
            or p.username
            or p.password
            or p.port not in (None, 443)
            or p.fragment
        ):
            raise ValueError("Callback host is not approved")
        return p

    def post(self, url, body, headers):
        p = self.validate(url)
        if len(body) > 262144:
            raise ValueError("Event too large")
        if any(
            os.environ.get(n)
            for n in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            )
        ):
            raise RuntimeError("Proxy transport unsupported; no direct fallback")
        ips = [str(r[4][0]) for r in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)]
        if not ips or any(
            not ip.is_global or ip.is_multicast or ip.is_reserved
            for ip in map(ipaddress.ip_address, ips)
        ):
            raise ValueError("Non-public callback address")
        conn = PinnedHTTPSConnection(p.hostname, timeout=10, context=ssl.create_default_context())
        conn._create_connection = (
            lambda _address, timeout, source_address: socket.create_connection(
                (ips[0], 443), timeout, source_address
            )
        )
        try:
            conn.request(
                "POST", (p.path or "/") + ("?" + p.query if p.query else ""), body, headers
            )
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
