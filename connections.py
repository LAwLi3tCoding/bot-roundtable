"""Observed local protocol access, never inferred vendor login or online status."""

import re
import time

from roundtable import Problem
from outbound import outbound_diagnostics


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
        return [
            dict(row) | {"vendor_account_verified": False}
            for row in self.store.db.execute(
                "SELECT a.id,COALESCE(b.name,a.id) AS name,a.kind,p.observed,p.nonce FROM agents a LEFT JOIN bots b ON b.id=a.id LEFT JOIN connection_probes p "
                "ON p.room=a.room AND p.agent=a.id AND p.epoch=a.token WHERE a.room=?",
                (room,),
            )
        ]


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
