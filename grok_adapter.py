"""Opt-in Grok routine dispatch. A 200 response is acceptance, never a reply.

No credentials or outbound URLs can be chosen by room messages. This adapter is
an operator-side library; it is deliberately not enabled by the demo server.
"""

import http.client
import ipaddress
import json
import os
import socket
import ssl
import time
import math
from urllib.parse import urlsplit
from collections.abc import Callable


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    _create_connection: Callable[..., socket.socket]


class GrokWebhook:
    def __init__(self, endpoint: str, key: str, allowed_host: str):
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname != allowed_host
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.fragment
        ):
            raise ValueError("Use an operator-approved HTTPS endpoint on port 443")
        if not key or "\r" in key or "\n" in key:
            raise ValueError("Invalid bearer key")
        self.host = parsed.hostname
        self.path = parsed.path or "/"
        if parsed.query:
            self.path += "?" + parsed.query
        self.key = key

    def dispatch(self, job: dict) -> dict:
        deadline = job.get("deadline")
        if (
            not isinstance(deadline, (int, float))
            or isinstance(deadline, bool)
            or not math.isfinite(deadline)
            or deadline <= time.time()
        ):
            raise ValueError("Job deadline is invalid or has expired")
        # Pin the validated address for the actual TLS connection. No redirect,
        # DNS rebinding, proxy auto-discovery, or URL from untrusted message data.
        if any(
            os.environ.get(name)
            for name in (
                "HTTPS_PROXY",
                "HTTP_PROXY",
                "ALL_PROXY",
                "https_proxy",
                "http_proxy",
                "all_proxy",
            )
        ):
            raise RuntimeError("Proxy-only environments are not supported; no direct fallback")
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        ips = [str(entry[4][0]) for entry in addresses]
        if not ips or any(
            not address.is_global or address.is_multicast or address.is_reserved
            for address in map(ipaddress.ip_address, ips)
        ):
            raise ValueError("Endpoint resolves to a non-public address")
        connection = PinnedHTTPSConnection(
            self.host, timeout=10, context=ssl.create_default_context()
        )
        connection._create_connection = (
            lambda _address, timeout, source_address: socket.create_connection(
                (ips[0], 443), timeout, source_address
            )
        )
        payload_data = {k: job[k] for k in ("id", "room", "run", "deadline", "messages")}
        if "phase" in job:
            payload_data["phase"] = job["phase"]
        payload = json.dumps(payload_data).encode()
        if len(payload) > 100000:
            raise ValueError("Payload too large")
        try:
            connection.request(
                "POST",
                self.path,
                body=payload,
                headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
            )
            status = connection.getresponse().status
            if status != 200:
                raise RuntimeError("Routine did not accept dispatch")
            return {"accepted": True, "completed": False, "job_id": job["id"]}
        finally:
            connection.close()


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Explicitly dispatch ONE mailbox job to a configured Grok routine"
    )
    parser.add_argument("--dispatch", action="store_true", required=True)
    parser.parse_args()
    try:
        adapter = GrokWebhook(
            os.environ["GROK_ROUTINE_URL"],
            os.environ["GROK_ROUTINE_KEY"],
            os.environ["GROK_ALLOWED_HOST"],
        )
        job = json.loads(sys.stdin.read(100001))
        print(json.dumps(adapter.dispatch(job)))
    except Exception:
        # The underlying exception can contain URL or network details.
        print(
            "Dispatch failed or outcome uncertain; inspect the Bot chat before retrying.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
