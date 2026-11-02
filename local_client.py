"""Narrow loopback protocol client for a bot's own authorized local tools.

No vendor process control, shell execution, model API, redirects or public URL.
Credentials come from environment references, never command-line arguments.
"""

import math
import hashlib
import argparse
import http.client
import json
import os
import re
import secrets
import sys
import time
import tempfile
import threading
import socket
import select
from pathlib import Path
from state_paths import state_dir
from urllib.parse import urlsplit

from outbound import outbound_diagnostics


_WAIT_SLOTS = threading.BoundedSemaphore(4)


class LocalFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


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
        self.room, self.agent = room, agent

    def call(self, operation, payload=None, timeout=10, _state=None):
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
            "mentions": "/mentions",
            "message": "/messages",
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
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        if _state is not None:
            _state["connection"] = conn
        try:
            if _state is not None and _state["cancelled"].is_set():
                raise LocalFailure("wait_timeout")
            conn.request(
                method,
                self.prefix + routes[operation],
                body,
                {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
            )
            if _state is not None and _state["cancelled"].is_set():
                raise LocalFailure("wait_timeout")
            if _state is not None:
                _state["socket"] = conn.sock
            response = conn.getresponse()
            if response.status in (401, 403):
                raise LocalFailure("authorization_rejected")
            raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ValueError("Response too large")
            if response.status != 200 and response.status != 201:
                raise ValueError(f"Local service rejected operation ({response.status})")
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                raise LocalFailure("protocol_mismatch") from None
            if operation in ("doctor", "capabilities", "probe") and (
                not isinstance(result, dict) or result.get("protocol") != "roundtable-local-v1"
            ):
                raise LocalFailure("protocol_mismatch")
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
                    "terminal_worker": result.get("terminal_worker", {"state": "unavailable"}),
                    "outbound_backend": result.get(
                        "outbound_backend", {"configured": False, "reason": "unavailable"}
                    ),
                    "outbound_local": outbound_diagnostics(),
                    "secrets_included": False,
                }
            return result
        except LocalFailure:
            raise
        except (OSError, http.client.HTTPException):
            raise LocalFailure("backend_unreachable") from None
        except (ValueError, TypeError, AttributeError):
            raise LocalFailure("protocol_mismatch") from None
        finally:
            conn.close()

    def _wait_query(self, task_id, timeout):
        # A stuck DNS/connect/read retains its slot until it really ends. Repeated
        # calls cannot accumulate unbounded threads; there is no direct fallback.
        deadline = time.monotonic() + timeout
        if not _WAIT_SLOTS.acquire(blocking=False):
            raise LocalFailure("wait_capacity_exhausted")
        done = threading.Event()
        state: dict = {"cancelled": threading.Event()}
        outcome = []

        def request():
            try:
                outcome.append(
                    self.call("task", {"task_id": task_id}, timeout=min(10, timeout), _state=state)
                )
            except Exception as exc:
                outcome.append(exc)
            finally:
                _WAIT_SLOTS.release()
                done.set()

        threading.Thread(target=request, daemon=True).start()
        if not done.wait(max(0, deadline - time.monotonic())):
            state["cancelled"].set()
            conn = state.get("connection")
            sock = state.get("socket") or getattr(conn, "sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            raise LocalFailure("wait_timeout")
        result = outcome[0]
        if isinstance(result, Exception):
            raise result
        return result

    def wait(self, task_id, timeout=600, interval=1):
        """Bounded polling; a local wait timeout does not cancel the server task."""
        if (
            not re.fullmatch(r"[a-f0-9]{24}", task_id)
            or not math.isfinite(timeout)
            or not 0 < timeout <= 86400
        ):
            raise ValueError("Invalid task ID or wait timeout")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LocalFailure("wait_timeout")
            snapshot = self._wait_query(task_id, remaining)
            if snapshot["task"]["status"] != "running":
                return snapshot
            time.sleep(min(interval, max(0, deadline - time.monotonic())))

    def roundtrip(self, worker, evidence_path, timeout=600, test=False):
        """An explicit one-assignment read-only test, not proof of vendor identity."""
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", worker) or worker == self.agent:
            raise ValueError("Invalid roundtrip worker")
        if not math.isfinite(timeout) or not 30 <= timeout <= 86400 or int(timeout) != timeout:
            raise ValueError("Roundtrip timeout must be an integer from 30 to 86400 seconds")
        nonce = secrets.token_hex(16)
        created = self.call(
            "create",
            {
                "title": "Read-only connectivity roundtrip",
                "context": "Explicit operator connectivity test; no business task or tool authority.",
                "assignments": [
                    {
                        "worker": worker,
                        "instruction": "Read-only connectivity test. Return exactly: roundtrip:"
                        + nonce
                        + ". Do not run commands, change files, access accounts, or delegate tasks.",
                    }
                ],
                "budget": 1,
                "timeout_seconds": int(timeout),
                "request_id": "roundtrip-" + nonce,
            },
        )
        evidence = {
            "version": 1,
            "source": "local-client",
            "observed_at": time.time(),
            "scope": {"room": self.room, "agent": self.agent, "worker": worker},
            "task_id": created["task_id"],
            "assignment_id": None,
            "test": bool(test),
            "status": "unknown",
            "correlated": False,
            "vendor_identity_verified": False,
            "expected_result_digest": hashlib.sha256(("roundtrip:" + nonce).encode()).hexdigest(),
            "summary": "Awaiting worker result",
        }
        save_evidence(evidence_path, evidence)
        try:
            snapshot = self.wait(created["task_id"], timeout)
            assignment = snapshot["assignments"][0]
            evidence.update(
                assignment_id=assignment["id"],
                status=snapshot["task"]["status"],
                correlated=assignment["result"].strip() == "roundtrip:" + nonce,
                summary=assignment["result"][:500],
                observed_at=time.time(),
            )
        except LocalFailure as exc:
            evidence.update(summary=exc.code, observed_at=time.time())
            save_evidence(evidence_path, evidence)
            raise
        save_evidence(evidence_path, evidence)
        return evidence

    def evidence(self, path):
        """Read scoped local evidence; operator observations are attestations only."""
        try:
            with Path(path).open() as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise ValueError("Evidence too large")
            item = json.loads(raw)
            scope = item["scope"]
            if scope["room"] != self.room or scope["agent"] != self.agent:
                raise ValueError("Evidence scope mismatch")
            snapshot = self.call("task", {"task_id": item["task_id"]})
            assignment = next(
                a for a in snapshot["assignments"] if a["id"] == item["assignment_id"]
            )
            verified = (
                item.get("correlated") is True
                and item["status"] == "completed"
                and snapshot["task"]["status"] == "completed"
                and assignment["worker"] == scope["worker"]
                and hashlib.sha256(assignment["result"].strip().encode()).hexdigest()
                == item.get("expected_result_digest")
            )
            observations = item.get("operator_observations", {})
            result = {
                "protocol_roundtrip_verified": {
                    "verified": verified,
                    "source": item["source"],
                    "observed_at": item["observed_at"],
                    "scope": scope,
                    "test": item.get("test", True),
                    "task_id": item["task_id"],
                }
            }
            for name in ("native_roundtrip", "wake"):
                observation = observations.get(name, {})
                confirmed = (
                    verified
                    and item.get("test") is False
                    and observation.get("confirmed") is True
                    and observation.get("source") == "operator"
                    and observation.get("task_id") == item["task_id"]
                    and observation.get("assignment_id") == item["assignment_id"]
                    and type(observation.get("observed_at")) in (int, float)
                    and math.isfinite(observation["observed_at"])
                    and item["observed_at"] <= observation["observed_at"] <= time.time()
                )
                result[name + "_verified"] = {
                    "verified": confirmed,
                    "evidence": "local operator attestation; not vendor identity proof"
                    if confirmed
                    else "no scoped native operator observation",
                    "vendor_identity_verified": False,
                }
            return result
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            return {
                "protocol_roundtrip_verified": {
                    "verified": False,
                    "reason": "evidence_unavailable_or_invalid",
                }
            }


def save_evidence(path, evidence):
    """Atomic private evidence file, no credentials or leases."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".roundtrip-", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(evidence, stream)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json_stdin(timeout=2, limit=32768):
    """Shared bounded input for native CLI and managed origin create. No interactive wait."""
    if sys.stdin.isatty():
        raise ValueError("JSON stdin required")
    raw = bytearray()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([sys.stdin], [], [], remaining)[0]:
            raise ValueError("JSON stdin timeout")
        chunk = os.read(sys.stdin.fileno(), limit + 1 - len(raw))
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > limit:
            raise ValueError("Payload too large")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=[
            "probe",
            "wait",
            "roundtrip",
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
            "mentions",
            "message",
        ],
    )
    parser.add_argument("task_id", nargs="?")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--worker", default="dot")
    parser.add_argument("--body", help="Context body with a positional task ID")
    parser.add_argument(
        "--evidence",
        default=os.environ.get("ROUNDTABLE_EVIDENCE", str(state_dir() / "roundtrip.json")),
    )
    parser.add_argument("--test", action="store_true", help="Mark synthetic worker evidence")
    args = parser.parse_args()
    phase = "configuration_missing"
    try:
        if any(
            not os.environ.get(n)
            for n in ("ROUNDTABLE_ROOM", "ROUNDTABLE_AGENT", "ROUNDTABLE_TOKEN")
        ):
            raise LocalFailure("configuration_missing")
        phase = "configuration_invalid"
        client = LocalClient(
            os.environ.get("ROUNDTABLE_URL", "http://127.0.0.1:8765"),
            os.environ.get("ROUNDTABLE_ROOM", ""),
            os.environ.get("ROUNDTABLE_AGENT", ""),
            os.environ.get("ROUNDTABLE_TOKEN", ""),
        )
        phase = "request_invalid"
        if args.task_id and args.operation not in ("wait", "task", "context"):
            raise ValueError("Unexpected task ID")
        if args.body is not None and (args.operation != "context" or not args.task_id):
            raise ValueError("Body requires context task ID")
        if args.operation == "wait":
            print(json.dumps(client.wait(args.task_id or "", args.timeout), ensure_ascii=False))
            return
        if args.operation == "roundtrip":
            print(
                json.dumps(
                    client.roundtrip(args.worker, args.evidence, args.timeout, args.test),
                    ensure_ascii=False,
                )
            )
            return
        data = None
        if args.operation not in ("probe", "doctor", "capabilities", "tasks", "inbox"):
            if args.task_id:
                if not re.fullmatch(r"[a-f0-9]{24}", args.task_id):
                    raise ValueError("Invalid task ID")
                # Positional mode never waits for stdin; reject already supplied JSON.
                if not sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]:
                    if os.read(sys.stdin.fileno(), 1):
                        raise ValueError("Task ID conflicts with stdin payload")
                data = {"task_id": args.task_id}
                if args.operation == "context":
                    if args.body is None:
                        raise ValueError("Context body required")
                    data["body"] = args.body
                    data["request_id"] = "context-" + secrets.token_hex(16)
            else:
                data = read_json_stdin()
        result = client.call(args.operation, data)
        if args.operation == "doctor":
            result.update(client.evidence(args.evidence))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        code = exc.code if isinstance(exc, LocalFailure) else phase
        # Network exceptions may include secrets/URLs; never echo their details.
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": code,
                    "next": "Check loopback service, scoped environment references and payload; no vendor login was attempted.",
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
