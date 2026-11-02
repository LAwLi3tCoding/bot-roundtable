"""Opt-in Grok routine dispatch. A 200 response is acceptance, never a reply.

No credentials or outbound URLs can be chosen by room messages. This adapter is
an operator-side library; it is deliberately not enabled by the demo server.
"""

import http.client
import ipaddress
import json
import re
import os
import socket
import ssl
import time
import math
from urllib.parse import urlsplit
from collections.abc import Callable
from outbound import canonical_host, proxy_config, OutboundNotSentError, OutboundConfig


NOTIFICATION_KINDS = ("task.assigned", "task.updated", "task.finished", "mention")
FINISHED_STATUSES = ("completed", "failed", "timeout", "cancelled")


def notification_body(kind, item_id, status=None):
    """Validate and build the webhook body shared with roundtable.notification.

    Rules: kind is one of NOTIFICATION_KINDS. task.* ids are 24 lowercase hex
    characters; mention ids are positive decimal message ids as strings.
    task.finished requires a finished status; task.updated may carry a status;
    task.assigned and mention carry none. No other keys are ever sent.
    """
    if kind not in NOTIFICATION_KINDS or not isinstance(item_id, str):
        raise ValueError("Invalid notification")
    if kind == "mention":
        if not re.fullmatch(r"[1-9][0-9]{0,17}", item_id) or status is not None:
            raise ValueError("Invalid mention notification")
    elif not re.fullmatch(r"[a-f0-9]{24}", item_id):
        raise ValueError("Invalid task notification")
    if kind == "task.finished" and status not in FINISHED_STATUSES:
        raise ValueError("Finished notifications require a finished status")
    if kind == "task.assigned" and status is not None:
        raise ValueError("Assigned notifications carry no status")
    if kind == "task.updated" and status is not None and not re.fullmatch(r"[a-z_]{1,32}", status):
        raise ValueError("Invalid task status")
    body = {"kind": kind, "id": item_id}
    if status is not None:
        body["status"] = status
    return body


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    _create_connection: Callable[..., socket.socket]


class GrokWebhook:
    def __init__(self, endpoint: str, key: str, allowed_host: str):
        if not isinstance(endpoint, str) or any(ord(c) <= 32 for c in endpoint):
            raise ValueError("Invalid routine endpoint")
        parsed = urlsplit(endpoint)
        host = canonical_host(parsed.hostname)
        allowed = canonical_host(allowed_host)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or host != allowed
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.fragment
        ):
            raise ValueError("Use an operator-approved HTTPS endpoint on port 443")
        if not key or "\r" in key or "\n" in key:
            raise ValueError("Invalid bearer key")
        self.host = host
        self.path = parsed.path or "/"
        if parsed.query:
            self.path += "?" + parsed.query
        self.key = key

    def preflight(self):
        """Validate operator proxy configuration before reserving a delivery."""
        return OutboundConfig(proxy_config())

    def dispatch(self, job: dict) -> dict:
        deadline = job.get("deadline")
        if (
            not isinstance(deadline, (int, float))
            or isinstance(deadline, bool)
            or not math.isfinite(deadline)
            or deadline <= time.time()
        ):
            raise ValueError("Job deadline is invalid or has expired")
        if any(k not in job for k in ("id", "room", "run", "messages")):
            raise ValueError("Incomplete job")
        payload_data = {k: job[k] for k in ("id", "room", "run", "deadline", "messages")}
        if "phase" in job:
            payload_data["phase"] = job["phase"]
        self._post(json.dumps(payload_data).encode())
        return {"accepted": True, "completed": False, "job_id": job["id"]}

    def notify(
        self, kind: str, item_id: str, status=None, *, cancelled=None, state=None, transport=None
    ) -> dict:
        """Send one generic wake hint (kind + id + optional status), never contents."""
        body = notification_body(kind, item_id, status)
        self._post(json.dumps(body).encode(), cancelled, state, transport)
        return {"accepted": True, **body}

    def dispatch_terminal(self, task_id: str, status: str, **kwargs) -> dict:
        """A task this bot originated finished; delivered as kind task.finished."""
        return self.notify("task.finished", task_id, status, **kwargs)

    def _post(self, payload: bytes, cancelled=None, state=None, transport=None) -> None:
        config = transport if transport is not None else self.preflight()
        proxy = config.proxy
        ips = []
        if not proxy:
            try:
                addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
                ips = [str(entry[4][0]) for entry in addresses]
                if not ips or any(
                    not address.is_global or address.is_multicast or address.is_reserved
                    for address in map(ipaddress.ip_address, ips)
                ):
                    raise ValueError()
            except (OSError, ValueError):
                raise OutboundNotSentError("outbound_resolution_not_sent") from None
        connection: PinnedHTTPSConnection
        if cancelled is not None or proxy:
            import threading
            from event_delivery import DirectHTTPSConnection, ConnectHTTPSConnection

            if cancelled is None:
                cancelled = threading.Event()
                state = {"deadline": time.monotonic() + 20}

            if state is None or cancelled.is_set() or time.monotonic() >= state["deadline"]:
                raise TimeoutError("Terminal delivery cancelled")
            if proxy:
                connection = ConnectHTTPSConnection(
                    self.host,
                    self.host,
                    proxy,
                    state["deadline"] - time.monotonic(),
                    ssl.create_default_context(),
                    state,
                    cancelled,
                )
            else:
                connection = DirectHTTPSConnection(
                    self.host,
                    ips[0],
                    state["deadline"] - time.monotonic(),
                    ssl.create_default_context(),
                    state,
                    cancelled,
                )
            state["connection"] = connection
        else:
            connection = PinnedHTTPSConnection(
                self.host, timeout=10, context=ssl.create_default_context()
            )
            connection._create_connection = (
                lambda _address, timeout, source_address: socket.create_connection(
                    (ips[0], 443), timeout, source_address
                )
            )
        if len(payload) > 100000:
            raise ValueError("Payload too large")
        try:
            if cancelled is not None and cancelled.is_set():
                raise TimeoutError("Terminal delivery cancelled")
            if cancelled is not None:
                try:
                    connection.connect()
                except Exception:
                    raise OutboundNotSentError("outbound_connection_not_sent") from None
            connection.request(
                "POST",
                self.path,
                body=payload,
                headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
            )
            status = connection.getresponse().status
            if status != 200:
                raise RuntimeError("Routine did not accept dispatch")
            return None
        finally:
            connection.close()

    def dispatch_assignment(self, assignment: dict) -> dict:
        """Explicit wake hint from an authorized inbox; never claim or complete work."""
        if assignment.get("status") != "queued":
            raise ValueError("Only queued assignments may request a wake")
        required = ("id", "task_id", "origin", "context", "instruction")
        if any(not isinstance(assignment.get(k), str) or not assignment[k] for k in required):
            raise ValueError("Use a current scoped assignment inbox record")
        room = assignment.get("room")
        if not isinstance(room, str) or not room:
            raise ValueError("Explicit scoped room required")
        result = self.dispatch(
            {
                "id": assignment["id"],
                "room": room,
                "run": assignment["task_id"],
                "deadline": assignment.get("deadline"),
                "phase": "assignment",
                "messages": [
                    {"sender": assignment["origin"], "body": assignment["context"]},
                    {"sender": assignment["origin"], "body": assignment["instruction"]},
                ],
            }
        )
        return {
            "accepted": result["accepted"],
            "completed": False,
            "task_id": assignment["task_id"],
            "assignment_id": assignment["id"],
        }


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Explicitly dispatch ONE mailbox job to a configured Grok routine"
    )
    parser.add_argument("--dispatch", action="store_true", required=True)
    parser.add_argument(
        "--assignment",
        action="store_true",
        help="Use a current scoped task assignment instead of a discussion job",
    )
    args = parser.parse_args()
    try:
        adapter = GrokWebhook(
            os.environ["GROK_ROUTINE_URL"],
            os.environ["GROK_ROUTINE_KEY"],
            os.environ["GROK_ALLOWED_HOST"],
        )
        job = json.loads(sys.stdin.read(100001))
        print(
            json.dumps(
                adapter.dispatch_assignment(job) if args.assignment else adapter.dispatch(job)
            )
        )
    except Exception:
        # The underlying exception can contain URL or network details.
        print(
            "Dispatch failed or outcome uncertain; inspect the Bot chat before retrying.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
