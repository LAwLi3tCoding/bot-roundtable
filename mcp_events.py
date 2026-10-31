"""Opt-in MCP Events extension over the official SDK's authenticated HTTP endpoint.

The pinned SDK handles core MCP; this module implements the documented draft
Events methods, not polling/streaming delivery. No OAuth implementation is implied.
"""

import asyncio
import hashlib
import hmac
import http.client
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from starlette.responses import JSONResponse

from event_delivery import encode, signed_headers, signing_key
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

EVENTS = [
    {
        "name": name,
        "description": description,
        "delivery": ["webhook"],
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        "payloadSchema": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in ("task_id", "assignment_id", "kind")},
            "required": ["task_id", "assignment_id", "kind"],
            "additionalProperties": False,
        },
    }
    for name, description, properties in [
        (
            "handoff.available",
            "A handoff is available for this authenticated bot; read its own inbox.",
            {},
        ),
        (
            "task.updated",
            "A task this bot originated changed; retrieve it for results. Self-authored changes do not notify.",
            {"task_id": {"type": "string"}},
        ),
    ]
]


class EventError(Exception):
    def __init__(self, code, reason):
        self.code, self.reason = code, reason


class EventBroker:
    def __init__(self, path, verifier, transport):
        self.verifier, self.transport = verifier, transport
        self.lock = threading.RLock()
        if path != ":memory:":
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise ValueError("Subscription DB must not be a symlink")
            fd = os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            if os.name != "nt" and target.stat().st_mode & 0o077:
                raise ValueError("Subscription DB must be private (0600)")
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS subscriptions(
                id TEXT PRIMARY KEY, principal TEXT, name TEXT, arguments TEXT,
                url TEXT, secret TEXT, previous TEXT, rotate_until REAL,
                expires REAL, cursor INTEGER, verified REAL, last_error TEXT);
            CREATE TABLE IF NOT EXISTS deliveries(
                subscription TEXT,event_id TEXT,body BLOB,attempt INTEGER,next_try REAL,
                PRIMARY KEY(subscription,event_id));
        """)
        self.db.commit()

    def feed(self, grant, name, arguments, after):
        conn = http.client.HTTPConnection(self.verifier.host, self.verifier.port, timeout=5)
        try:
            conn.request(
                "POST",
                f"/api/rooms/{grant.room}/agents/{grant.agent}/peer/event-feed",
                encode({"name": name, "arguments": arguments, "after": after}),
                {"Authorization": "Bearer " + grant.token, "Content-Type": "application/json"},
            )
            response = conn.getresponse()
            raw = response.read(262145)
            if response.status != 200 or len(raw) > 262144:
                raise EventError(-32602, "event_scope_denied")
            return json.loads(raw)
        finally:
            conn.close()

    def principal(self):
        _, token, _ = self.verifier.identity()
        key = hashlib.sha256(token.encode()).hexdigest()
        return key, self.verifier.grants[key]

    def identity(self, principal, params, subscribing):
        if not isinstance(params, dict) or set(params) - {
            "name",
            "arguments",
            "delivery",
            "cursor",
            "ttlMs",
        }:
            raise EventError(-32602, "invalid_subscription")
        name, arguments, delivery = (
            params.get("name"),
            params.get("arguments"),
            params.get("delivery"),
        )
        if (
            name not in ("handoff.available", "task.updated")
            or not isinstance(arguments, dict)
            or set(arguments) != ({"task_id"} if name == "task.updated" else set())
            or not isinstance(delivery, dict)
            or delivery.get("mode") != "webhook"
            or set(delivery) != ({"mode", "url", "secret"} if subscribing else {"mode", "url"})
            or params.get("cursor") is not None
        ):
            raise EventError(-32602, "invalid_subscription")
        try:
            self.transport.validate(delivery.get("url"))
        except (ValueError, TypeError):
            raise EventError(-32015, "callback_not_allowed") from None
        canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
        sid = (
            "sub_"
            + hashlib.sha256(encode([principal, delivery["url"], name, canonical])).hexdigest()
        )
        return sid, name, arguments, delivery, canonical

    def rpc(self, method, params):
        principal, grant = self.principal()
        if method == "events/list":
            if not isinstance(params, dict) or params.get("cursor") is not None:
                raise EventError(-32602, "invalid_cursor")
            return {"events": EVENTS}
        if method not in ("events/subscribe", "events/unsubscribe"):
            raise EventError(-32601, "method_not_found")
        subscribing = method == "events/subscribe"
        sid, name, arguments, delivery, canonical = self.identity(principal, params, subscribing)
        with self.lock:
            if not subscribing:
                self.db.execute("DELETE FROM deliveries WHERE subscription=?", (sid,))
                self.db.execute(
                    "DELETE FROM subscriptions WHERE id=? AND principal=?", (sid, principal)
                )
                self.db.commit()
                return {}
            # Validate resource scope before resolving/contacting any callback.
            initial = self.feed(grant, name, arguments, None)
            ttl = params.get("ttlMs", 3600000)
            if ttl is None:
                ttl = 3600000  # Never grant perpetual subscriptions.
            if type(ttl) is not int or ttl <= 0:
                raise EventError(-32602, "invalid_ttl")
            ttl = min(ttl, 3600000)
            try:
                signing_key(delivery.get("secret"))
            except ValueError:
                raise EventError(-32602, "invalid_signing_secret") from None
            now = time.time()
            self.cleanup(now)
            old = self.db.execute("SELECT * FROM subscriptions WHERE id=?", (sid,)).fetchone()
            if (
                not old
                and self.db.execute(
                    "SELECT COUNT(*) FROM subscriptions WHERE principal=?", (principal,)
                ).fetchone()[0]
                >= 10
            ):
                raise EventError(-32602, "subscription_limit")
            if (
                not old
                and self.db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] >= 100
            ):
                raise EventError(-32602, "subscription_limit")
            verified = old["verified"] if old else 0
            if not old or old["secret"] != delivery["secret"] or now - old["verified"] > 60:
                challenge = secrets.token_urlsafe(32)
                body = encode({"type": "verification", "challenge": challenge})
                event_id = "verify_" + secrets.token_hex(12)
                try:
                    status, raw = self.transport.post(
                        delivery["url"],
                        body,
                        signed_headers(delivery["secret"], sid, event_id, body),
                    )
                    echoed = json.loads(raw).get("challenge")
                    if (
                        not 200 <= status < 300
                        or not isinstance(echoed, str)
                        or not hmac.compare_digest(echoed, challenge)
                    ):
                        raise ValueError("challenge_failed")
                except Exception:
                    raise EventError(-32015, "challenge_failed") from None
                if time.time() - now > 15 or not self.verifier.still_authorized(grant):
                    raise EventError(-32015, "verification_expired_or_access_revoked")
                verified = time.time()
            changed = old and old["secret"] != delivery["secret"]
            previous = old["secret"] if changed else old["previous"] if old else ""
            rotation = now + 60 if changed else old["rotate_until"] if old else 0
            expiry = time.time() + ttl / 1000
            self.db.execute(
                "INSERT OR REPLACE INTO subscriptions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    principal,
                    name,
                    canonical,
                    delivery["url"],
                    delivery["secret"],
                    previous,
                    rotation,
                    expiry,
                    old["cursor"] if old else initial["cursor"],
                    verified,
                    "",
                ),
            )
            self.db.commit()
            return {
                "id": sid,
                "refreshBefore": datetime.fromtimestamp(expiry, timezone.utc).isoformat(),
                "cursor": None,
                "truncated": False,
            }

    def cleanup(self, now):
        self.db.execute(
            "DELETE FROM deliveries WHERE subscription IN (SELECT id FROM subscriptions WHERE expires<=?)",
            (now,),
        )
        self.db.execute("DELETE FROM subscriptions WHERE expires<=?", (now,))
        self.db.execute("UPDATE subscriptions SET previous='' WHERE rotate_until<=?", (now,))
        self.db.commit()

    def dispatch_once(self):
        """Internal durable-outbox scan; external delivery is signed HTTPS only."""
        with self.lock:
            now = time.time()
            self.cleanup(now)
            for sub in self.db.execute("SELECT * FROM subscriptions ORDER BY id").fetchall():
                grant = self.verifier.grants.get(sub["principal"])
                if not grant or not self.verifier.still_authorized(grant):
                    self.db.execute(
                        "UPDATE subscriptions SET expires=0,last_error='access_revoked' WHERE id=?",
                        (sub["id"],),
                    )
                    self.db.commit()
                    continue
                pending = self.db.execute(
                    "SELECT 1 FROM deliveries WHERE subscription=?", (sub["id"],)
                ).fetchone()
                try:
                    # Also rechecks task-level scope on every delivery iteration.
                    feed = self.feed(
                        grant,
                        sub["name"],
                        json.loads(sub["arguments"]),
                        sub["cursor"] if not pending else None,
                    )
                except Exception:
                    self.db.execute(
                        "UPDATE subscriptions SET last_error='backend_unavailable_or_scope_denied' WHERE id=?",
                        (sub["id"],),
                    )
                    self.db.commit()
                    continue
                if not pending:
                    for event in feed["events"]:
                        self.db.execute(
                            "INSERT OR IGNORE INTO deliveries VALUES(?,?,?,0,0)",
                            (sub["id"], event["eventId"], encode(event)),
                        )
                    self.db.execute(
                        "UPDATE subscriptions SET cursor=? WHERE id=?", (feed["cursor"], sub["id"])
                    )
                    self.db.commit()
                # One delivery per subscription per scan, bounded retries, stable ID.
                row = self.db.execute(
                    "SELECT * FROM deliveries WHERE subscription=? ORDER BY rowid LIMIT 1",
                    (sub["id"],),
                ).fetchone()
                if not row or row["next_try"] > now or sub["expires"] <= time.time():
                    continue
                status = 0
                try:
                    headers = signed_headers(
                        sub["secret"],
                        sub["id"],
                        row["event_id"],
                        row["body"],
                        sub["previous"] if sub["rotate_until"] > time.time() else "",
                    )
                    status, _ = self.transport.post(sub["url"], row["body"], headers)
                except Exception:
                    pass  # Bounded retry; no URLs, payloads, secrets or raw errors in logs.
                attempt = row["attempt"] + 1
                transient = status == 0 or status == 429 or status >= 500
                if transient and attempt < 3:
                    self.db.execute(
                        "UPDATE deliveries SET attempt=?,next_try=? WHERE subscription=? AND event_id=?",
                        (attempt, time.time() + 5 * 2**attempt, sub["id"], row["event_id"]),
                    )
                else:
                    self.db.execute(
                        "DELETE FROM deliveries WHERE subscription=? AND event_id=?",
                        (sub["id"], row["event_id"]),
                    )
                error = "" if 200 <= status < 300 else "delivery_rejected_or_exhausted"
                self.db.execute(
                    "UPDATE subscriptions SET last_error=? WHERE id=?", (error, sub["id"])
                )
                if status == 410:
                    self.db.execute("UPDATE subscriptions SET expires=0 WHERE id=?", (sub["id"],))
                self.db.commit()


class EventsHTTP:
    """Draft methods extend, rather than replace, the SDK's JSON HTTP transport."""

    def __init__(self, app, broker):
        self.app, self.broker = app, broker

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":

            async def worker():
                while True:
                    try:
                        await asyncio.to_thread(self.broker.dispatch_once)
                    except Exception:
                        pass  # Do not leak callback secrets in exception logs.
                    await asyncio.sleep(2)

            task = asyncio.create_task(worker())
            try:
                await self.app(scope, receive, send)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            return
        if scope["type"] != "http" or scope.get("path") != "/mcp" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        chunks, raw = [], b""
        while True:
            item = await receive()
            if item["type"] == "http.disconnect":
                return
            chunks.append(item)
            raw += item.get("body", b"")
            if len(raw) > 32768:
                await JSONResponse({"error": "Request too large"}, status_code=413)(
                    scope, receive, send
                )
                return
            if not item.get("more_body", False):
                break
        try:
            request = json.loads(raw)
        except ValueError:
            request = {}
        if isinstance(request, dict) and str(request.get("method", "")).startswith("events/"):
            rid = request.get("id")
            headers = dict(scope.get("headers", []))
            try:
                accept = headers.get(b"accept", b"")
                version = headers.get(b"mcp-protocol-version", b"2025-03-26").decode(
                    "ascii", errors="replace"
                )
                if (
                    b"application/json" not in accept
                    or b"text/event-stream" not in accept
                    or version not in SUPPORTED_PROTOCOL_VERSIONS
                ):
                    raise EventError(-32600, "invalid_transport_headers")
                if (
                    request.get("jsonrpc") != "2.0"
                    or type(rid) not in (str, int)
                    or headers.get(b"content-type", b"").split(b";")[0] != b"application/json"
                ):
                    raise EventError(-32600, "invalid_request")
                result = await asyncio.to_thread(
                    self.broker.rpc, request["method"], request.get("params", {})
                )
                response = {"jsonrpc": "2.0", "id": rid, "result": result}
            except EventError as exc:
                response = {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {
                        "code": exc.code,
                        "message": "Event request rejected",
                        "data": {"reason": exc.reason},
                    },
                }
            except Exception:
                response = {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32603, "message": "Event service unavailable"},
                }
            await JSONResponse(response)(scope, receive, send)
            return

        async def replay():
            return chunks.pop(0) if chunks else await receive()

        start = None

        async def advertise(message):
            nonlocal start
            if isinstance(request, dict) and request.get("method") == "initialize":
                if message["type"] == "http.response.start":
                    start = message
                    return
                if message["type"] == "http.response.body" and start is not None:
                    body = message.get("body", b"")
                    try:
                        value = json.loads(body)
                        value["result"]["capabilities"]["events"] = {}
                        body = encode(value)
                    except (ValueError, KeyError, TypeError):
                        pass
                    start["headers"] = [
                        (k, v) for k, v in start["headers"] if k != b"content-length"
                    ] + [(b"content-length", str(len(body)).encode())]
                    await send(start)
                    await send(dict(message, body=body))
                    return
            await send(message)

        await self.app(scope, replay, advertise)
