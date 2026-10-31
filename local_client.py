"""Narrow loopback protocol client for a bot's own authorized local tools.

No vendor process control, shell execution, model API, redirects or public URL.
Credentials come from environment references, never command-line arguments.
"""

import argparse
import http.client
import json
import os
import re
import secrets
import sys
from urllib.parse import urlsplit


class LocalClient:
    def __init__(self, base, room, agent, token):
        parsed = urlsplit(base)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost")
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Loopback HTTP URL required")
        if not re.fullmatch(r"[a-f0-9]{24}", room) or not re.fullmatch(
            r"[a-z][a-z0-9-]{1,39}", agent
        ):
            raise ValueError("Scoped room and agent required")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            raise ValueError("Scoped agent credential required")
        self.host, self.port = parsed.hostname, parsed.port or 8765
        self.prefix = f"/api/rooms/{room}/agents/{agent}/peer"
        self.token = token

    def call(self, operation, payload=None):
        routes = {
            "probe": "/probe",
            "capabilities": "/capabilities",
            "doctor": "/capabilities",
            "tasks": "/tasks",
            "create": "/tasks",
            "task": "/tasks/query",
            "inbox": "/tasks/inbox",
            "claim": "/tasks/claim",
            "report": "/tasks/update",
            "context": "/tasks/context",
            "retry": "/tasks/retry",
            "cancel": "/tasks/cancel",
        }
        if operation not in routes:
            raise ValueError("Unsupported local operation")
        method = "GET" if operation in ("capabilities", "tasks", "doctor") else "POST"
        if operation == "probe":
            payload = {"nonce": secrets.token_urlsafe(18)}
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("JSON object required")
        body = json.dumps(payload or {}, ensure_ascii=False).encode() if method == "POST" else None
        if body and len(body) > 32768:
            raise ValueError("Payload exceeds 32768 bytes")
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            conn.request(
                method,
                self.prefix + routes[operation],
                body,
                {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
            )
            response = conn.getresponse()
            raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ValueError("Response too large")
            if response.status != 200 and response.status != 201:
                raise ValueError(f"Local service rejected operation ({response.status})")
            result = json.loads(raw)
            if operation == "probe" and (
                payload is None or result.get("nonce") != payload["nonce"]
            ):
                raise ValueError("Probe correlation failed")
            if operation == "doctor":
                return {
                    "configured": {
                        "verified": True,
                        "evidence": "validated scoped environment references",
                    },
                    "transport_verified": {
                        "verified": True,
                        "evidence": "authenticated loopback capabilities response",
                    },
                    "native_roundtrip_verified": {
                        "verified": False,
                        "reason": "requires actual native bot task and correlated result",
                    },
                    "wake_verified": {
                        "verified": False,
                        "reason": "requires actual provider subscription/routine and observed native response",
                    },
                    "secrets_included": False,
                }
            return result
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=[
            "probe",
            "doctor",
            "capabilities",
            "tasks",
            "task",
            "inbox",
            "create",
            "claim",
            "report",
            "context",
            "retry",
            "cancel",
        ],
    )
    args = parser.parse_args()
    try:
        client = LocalClient(
            os.environ.get("ROUNDTABLE_URL", "http://127.0.0.1:8765"),
            os.environ.get("ROUNDTABLE_ROOM", ""),
            os.environ.get("ROUNDTABLE_AGENT", ""),
            os.environ.get("ROUNDTABLE_TOKEN", ""),
        )
        data = None
        if args.operation not in ("probe", "doctor", "capabilities", "tasks", "inbox"):
            raw = sys.stdin.buffer.read(32769)
            if len(raw) > 32768:
                raise ValueError("Payload too large")
            data = json.loads(raw)
        print(json.dumps(client.call(args.operation, data), ensure_ascii=False))
    except Exception:
        # Network exceptions may include secrets/URLs; never echo their details.
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "local_connection_or_request_failed",
                    "next": "Check loopback service, scoped environment references and payload; no vendor login was attempted.",
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
