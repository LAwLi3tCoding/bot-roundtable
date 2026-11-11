"""Observed local protocol access, never inferred vendor login or online status."""

import re
import sqlite3
import time
from pathlib import Path

from roundtable import Problem
from outbound import outbound_diagnostics


def events_database(store):
    path = getattr(store, "path", None)
    if not path or path == ":memory:":
        return None
    database = Path(path).expanduser()
    if not database.is_file():
        return None
    events = database.parent / "events.db"
    return events if events.is_file() else None


def load_subscription_expiry(store, principals):
    """Latest expiry per principal; never returns URLs, secrets or raw tokens."""
    path = events_database(store)
    if path is None or not principals:
        return None
    placeholders = ",".join("?" * len(principals))
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            rows = db.execute(
                f"SELECT principal, MAX(expires) FROM subscriptions "
                f"WHERE principal IN ({placeholders}) GROUP BY principal",
                tuple(principals),
            ).fetchall()
    except sqlite3.Error:
        return None
    return {row[0]: row[1] for row in rows}


class Connections:
    def __init__(self, store):
        self.store = store
        store.db.execute("""CREATE TABLE IF NOT EXISTS connection_probes(
            room TEXT,agent TEXT,epoch TEXT,observed REAL,nonce TEXT,PRIMARY KEY(room,agent))""")
        columns = {row[1] for row in store.db.execute("PRAGMA table_info(connection_probes)")}
        if "nonce" not in columns:
            store.db.execute("ALTER TABLE connection_probes ADD COLUMN nonce TEXT")
        store.db.commit()

    def probe(self, room, agent, nonce):
        if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", nonce):
            raise Problem(400, "Use a fresh 16–80 character probe nonce")
        epoch = self.store.handoffs.member(room, "bot:" + agent)
        now = time.time()
        with self.store.transaction():
            self.store.db.execute(
                "INSERT OR REPLACE INTO connection_probes(room,agent,epoch,observed,nonce) VALUES(?,?,?,?,?)",
                (room, agent, epoch, now, nonce),
            )
        return {
            "protocol": "roundtable-local-v1",
            "room": room,
            "agent": agent,
            "nonce": nonce,
            "observed": now,
            "evidence": "scoped-credential-request",
            "vendor_account_verified": False,
        }

    def status(self, room):
        result = []
        with self.store.lock:
            rows = list(
                self.store.db.execute(
                    "SELECT a.id,a.token,COALESCE(b.name,a.id) AS name,a.kind,p.observed,p.nonce FROM agents a LEFT JOIN bots b ON b.id=a.id LEFT JOIN connection_probes p "
                    "ON p.room=a.room AND p.agent=a.id AND p.epoch=a.token WHERE a.room=?",
                    (room,),
                )
            )
        expiries = load_subscription_expiry(
            self.store, [row["token"] for row in rows if row["token"]]
        )
        now = time.time()
        with self.store.lock:
            for row in rows:
                value = dict(row)
                epoch = value.pop("token")
                if expiries is None:
                    subscription_state, subscription_evidence, subscription_expires_at = (
                        "unknown",
                        "events-db-unavailable",
                        None,
                    )
                else:
                    expiry = expiries.get(epoch)
                    subscription_evidence = "events-db"
                    if expiry is None:
                        subscription_state, subscription_expires_at = "missing", None
                    elif expiry > now:
                        subscription_state, subscription_expires_at = "valid", expiry
                    else:
                        subscription_state, subscription_expires_at = "expired", expiry
                task_events = self.store.db.execute(
                    "SELECT e.kind,e.created FROM task_events e JOIN tasks t ON t.id=e.task "
                    "JOIN assignments a ON a.id=e.assignment WHERE t.room=? AND a.worker=? "
                    "AND a.epoch=? AND e.actor=? AND e.kind IN ('claimed','completed','failed','progress') ORDER BY e.id DESC",
                    (room, row["id"], epoch, "bot:" + row["id"]),
                ).fetchall()
                last_claim = next(
                    (event["created"] for event in task_events if event["kind"] == "claimed"), None
                )
                replies = [event["created"] for event in task_events if event["kind"] != "claimed"]
                message = self.store.db.execute(
                    "SELECT MAX(created) FROM discussion_messages WHERE room=? AND sender=? AND sender_epoch=?",
                    (room, "bot:" + row["id"], epoch),
                ).fetchone()[0]
                if message is not None:
                    replies.append(message)
                last_reply = max(replies, default=None)
                activity = [
                    stamp
                    for stamp in (value["observed"], last_claim, last_reply)
                    if stamp is not None
                ]
                last_activity = max(activity, default=None)
                expires = last_activity + 120 if last_activity is not None else None
                value.update(
                    protocol_state=(
                        "unknown"
                        if expires is None
                        else "recent"
                        if time.time() <= expires
                        else "stale"
                    ),
                    activity_ttl_seconds=120,
                    activity_expires_at=expires,
                    vendor_account_verified=False,
                    last_claim=last_claim,
                    last_reply=last_reply,
                    last_activity=max(activity, default=None),
                    subscription_state=subscription_state,
                    subscription_evidence=subscription_evidence,
                    subscription_expires_at=subscription_expires_at,
                    activity_evidence="current-scoped-credential",
                )
                result.append(value)
        return result


def capabilities(worker=None):
    return {
        "outbound_backend": outbound_diagnostics(),
        "terminal_worker": worker.status() if worker else {"state": "disabled"},
        "protocol": "roundtable-local-v1",
        "local_http": True,
        "mcp_stdio": True,
        "mcp_http": "separate-authenticated-gateway",
        "computer_use_required": False,
        "vendor_accounts_verified": [],
        "providers": {
            "grok": {
                "local_api": "owner-enabled-local-execution",
                "wake": "routine-webhook-opt-in",
            },
            "dot": {
                "local_api": "connected-computer-path-unverified",
                "wake": "mcp-events-opt-in",
                "private_mcp": "secure-tunnel-requires-org-permissions",
                "hosted_auth": "oauth-required-not-implemented",
            },
            "ds-bot": {"mcp": "owner-configured-unverified"},
        },
    }
