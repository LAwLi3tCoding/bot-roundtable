"""Local-first room registry, scoped identities and bounded single-authority scheduler."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any


class Problem(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def text(value: Any, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Problem(400, f"Expected nonempty text, at most {maximum} characters")
    return value


class Store:
    def __init__(self, path: str = ":memory:", timeout: float = 60):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.timeout = timeout
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS rooms(id TEXT PRIMARY KEY, token TEXT, name TEXT);
        CREATE TABLE IF NOT EXISTS agents(room TEXT, id TEXT, kind TEXT, token TEXT,
          PRIMARY KEY(room,id));
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, room TEXT, request TEXT,
          plan TEXT, budget INTEGER, turn INTEGER, status TEXT, UNIQUE(room,request));
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, room TEXT,
          run TEXT, sender TEXT, source TEXT, body TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, room TEXT, run TEXT,
          agent TEXT, status TEXT, deadline REAL, reply TEXT);
        """)
        migrations = {
            "rooms": {"lead": "TEXT NOT NULL DEFAULT ''"},
            "agents": {"allowance": "INTEGER NOT NULL DEFAULT 0"},
            "runs": {"actor": "TEXT NOT NULL DEFAULT 'user'", "lead": "TEXT NOT NULL DEFAULT ''"},
        }
        for table, columns in migrations.items():
            existing = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}
            for column, sql_type in columns.items():
                if column not in existing:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS bots(id TEXT PRIMARY KEY, name TEXT, kind TEXT, description TEXT)"
        )
        for aid, name in (("demo-planner", "Demo Planner"), ("demo-critic", "Demo Critic")):
            self.db.execute(
                "INSERT OR IGNORE INTO bots VALUES (?,?,?,?)",
                (aid, name, "demo", "Deterministic demo / 确定性示例"),
            )
        # Never replay an uncertain external dispatch after a process restart.
        self.db.execute("UPDATE runs SET status='interrupted' WHERE status='running'")
        self.db.execute("UPDATE jobs SET status='interrupted' WHERE status='pending'")
        self.db.commit()
        from handoffs import Handoffs

        self.handoffs = Handoffs(self)

    @contextmanager
    def transaction(self):
        # Every nesting level has its own savepoint. Releasing an inner level
        # must not commit its caller's writes (sqlite connection contexts do).
        with self.lock:
            savepoint = "rt_" + secrets.token_hex(8)
            self.db.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
            except BaseException:
                self.db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.db.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self.db.execute(f"RELEASE SAVEPOINT {savepoint}")

    def room(self, name: str) -> dict:
        name = text(name, 80)
        rid, token = secrets.token_hex(12), secrets.token_urlsafe(32)
        with self.transaction():
            self.db.execute(
                "INSERT INTO rooms(id,token,name) VALUES (?,?,?)", (rid, digest(token), name)
            )
            for aid in ("demo-planner", "demo-critic"):
                self.db.execute(
                    "INSERT INTO agents(room,id,kind,token) VALUES (?,?,?,?)",
                    (rid, aid, "demo", ""),
                )
        return dict(id=rid, token=token, name=name)

    def create_group(self, name: str, bots: list | None = None) -> dict:
        if bots is None:
            return self.room(name)
        if (
            not isinstance(bots, list)
            or not 1 <= len(bots) <= 6
            or any(not isinstance(b, str) for b in bots)
            or len(set(bots)) != len(bots)
        ):
            raise Problem(400, "Choose 1–6 distinct registered bots")
        with self.transaction():
            for aid in bots:
                if not self.db.execute("SELECT 1 FROM bots WHERE id=?", (aid,)).fetchone():
                    raise Problem(400, "Registered bot not found")
            room = self.room(name)
            self.db.execute("DELETE FROM agents WHERE room=?", (room["id"],))
            room["agent_tokens"] = [self.join(room["id"], aid) for aid in bots]
            return room

    def authorize(self, room: str, token: str, agent: str | None = None):
        with self.lock:
            row = (
                self.db.execute("SELECT token FROM rooms WHERE id=?", (room,)).fetchone()
                if agent is None
                else self.db.execute(
                    "SELECT token FROM agents WHERE room=? AND id=?", (room, agent)
                ).fetchone()
            )
            if not row or not row["token"] or not hmac.compare_digest(row["token"], digest(token)):
                raise Problem(403, "Invalid room or agent credential")

    def add_agent(self, room: str, aid: str, kind: str = "mailbox") -> dict:
        import re

        if (
            not isinstance(aid, str)
            or aid == "user"
            or not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", aid)
            or kind not in ("mailbox", "grok", "demo", "dot", "other-bot")
        ):
            raise Problem(400, "Invalid agent id or kind")
        token = secrets.token_urlsafe(32)
        with self.transaction():
            self.idle(room)
            if (
                self.db.execute("SELECT COUNT(*) FROM agents WHERE room=?", (room,)).fetchone()[0]
                >= 6
            ):
                raise Problem(400, "A room can contain at most 6 bots")
            try:
                self.db.execute(
                    "INSERT INTO agents(room,id,kind,token) VALUES (?,?,?,?)",
                    (room, aid, kind, digest(token)),
                )
            except sqlite3.IntegrityError:
                raise Problem(409, "Agent already exists") from None
        return dict(id=aid, token=token, kind=kind)

    def message(self, room: str, run: str, sender: str, source: str, body: str):
        self.db.execute(
            "INSERT INTO messages(room,run,sender,source,body,created) VALUES (?,?,?,?,?,?)",
            (room, run, sender, source, body, time.time()),
        )

    def start(
        self, room: str, body: str, targets: list, budget: int, request: str, actor: str = "user"
    ) -> dict:
        text(body)
        text(request, 100)
        if (
            type(budget) is not int
            or not 1 <= budget <= 20
            or not isinstance(targets, list)
            or not 1 <= len(targets) <= 6
            or any(not isinstance(a, str) for a in targets)
            or len(set(targets)) != len(targets)
        ):
            raise Problem(400, "Choose 1–6 distinct agents and 1–20 total replies")
        with self.transaction():
            old = self.db.execute(
                "SELECT * FROM runs WHERE room=? AND request=?", (room, request)
            ).fetchone()
            if old:
                if old["actor"] != actor:
                    raise Problem(409, "Request ID belongs to another identity")
                return dict(old)
            if self.db.execute(
                "SELECT 1 FROM runs WHERE room=? AND status='running'", (room,)
            ).fetchone():
                raise Problem(409, "Stop or finish the current run first")
            for aid in targets:
                if not self.db.execute(
                    "SELECT 1 FROM agents WHERE room=? AND id=?", (room, aid)
                ).fetchone():
                    raise Problem(400, "Unknown agent in this room")
            room_row = self.db.execute("SELECT lead FROM rooms WHERE id=?", (room,)).fetchone()
            if not room_row:
                raise Problem(404, "Room not found")
            lead = room_row["lead"]
            if actor != "user":
                aid = actor.removeprefix("bot:")
                scope = self.db.execute(
                    "SELECT allowance FROM agents WHERE room=? AND id=?", (room, aid)
                ).fetchone()
                if not scope or scope["allowance"] < budget:
                    raise Problem(403, "Bot initiation allowance exhausted or not granted")
                if aid in targets or aid == lead:
                    raise Problem(403, "Self invocation is not allowed")
                self.db.execute(
                    "UPDATE agents SET allowance=allowance-? WHERE room=? AND id=?",
                    (budget, room, aid),
                )
            plan = [targets[i % len(targets)] for i in range(budget)]
            if lead:
                if budget < 3:
                    raise Problem(400, "Lead coordination requires at least 3 replies")
                peers = [aid for aid in targets if aid != lead]
                if not peers and budget > 1:
                    raise Problem(400, "Lead coordination needs another participant")
                plan = (
                    [lead]
                    if budget == 1
                    else [lead] + [peers[i % len(peers)] for i in range(budget - 2)] + [lead]
                )
            run = secrets.token_hex(12)
            self.db.execute(
                "INSERT INTO runs(id,room,request,plan,budget,turn,status,actor,lead) VALUES (?,?,?,?,?,0,?,?,?)",
                (run, room, request, json.dumps(plan), budget, "running", actor, lead),
            )
            self.message(room, run, actor, "human" if actor == "user" else "mcp", body)
            self.schedule(run)
            return dict(self.db.execute("SELECT * FROM runs WHERE id=?", (run,)).fetchone())

    def schedule(self, run: str):
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run,)).fetchone()
        if row["turn"] >= row["budget"]:
            self.db.execute("UPDATE runs SET status='completed' WHERE id=?", (run,))
            return
        agent = json.loads(row["plan"])[row["turn"] % len(json.loads(row["plan"]))]
        self.db.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,NULL)",
            (secrets.token_hex(16), row["room"], run, agent, "pending", time.time() + self.timeout),
        )

    def expire(self):
        with self.transaction():
            rows = self.db.execute(
                "SELECT * FROM jobs WHERE status='pending' AND deadline<=?", (time.time(),)
            ).fetchall()
            for row in rows:
                self.db.execute("UPDATE jobs SET status='timeout' WHERE id=?", (row["id"],))
                self.db.execute(
                    "UPDATE runs SET status='timeout' WHERE id=? AND status='running'",
                    (row["run"],),
                )
                logging.info("job_timeout job=%s", row["id"])

    def inbox(self, room: str, agent: str) -> list:
        self.expire()
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM jobs WHERE room=? AND agent=? AND status='pending'", (room, agent)
            ).fetchall()
            return [
                dict(
                    id=r["id"],
                    room=room,
                    run=r["run"],
                    deadline=r["deadline"],
                    phase=self.phase(r["run"]),
                    messages=[
                        dict(m)
                        for m in self.db.execute(
                            "SELECT sender,source,body FROM messages WHERE room=? AND run=? ORDER BY id",
                            (room, r["run"]),
                        )
                    ],
                )
                for r in rows
            ]

    def reply(self, room: str, agent: str, job: str, body: str, failed: bool = False) -> dict:
        text(body)
        if type(failed) is not bool:
            raise Problem(400, "failed must be boolean")
        with self.transaction():
            row = self.db.execute(
                "SELECT * FROM jobs WHERE id=? AND room=? AND agent=?", (job, room, agent)
            ).fetchone()
            if not row:
                raise Problem(404, "Job not found")
            fingerprint = digest(json.dumps([body, failed]))
            if row["status"] in ("done", "failed"):
                if row["reply"] != fingerprint:
                    raise Problem(409, "Conflicting duplicate reply")
                return dict(duplicate=True)
            if row["status"] != "pending":
                raise Problem(409, "Job is no longer active")
            if row["deadline"] <= time.time():
                # Check while holding the same lock as the reply write. Commit
                # expiration before raising; raising inside the transaction
                # would roll the timeout state back.
                self.db.execute("UPDATE jobs SET status='timeout' WHERE id=?", (job,))
                self.db.execute(
                    "UPDATE runs SET status='timeout' WHERE id=? AND status='running'",
                    (row["run"],),
                )
                logging.info("job_timeout job=%s", job)
            else:
                self.db.execute(
                    "UPDATE jobs SET status=?,reply=? WHERE id=?",
                    ("failed" if failed else "done", fingerprint, job),
                )
                kind = self.db.execute(
                    "SELECT kind FROM agents WHERE room=? AND id=?", (room, agent)
                ).fetchone()["kind"]
                self.message(room, row["run"], agent, kind + ("-error" if failed else ""), body)
                if failed:
                    self.db.execute("UPDATE runs SET status='failed' WHERE id=?", (row["run"],))
                else:
                    self.db.execute("UPDATE runs SET turn=turn+1 WHERE id=?", (row["run"],))
                    self.schedule(row["run"])
                logging.info("job_reply job=%s failed=%s", job, failed)
                return dict(duplicate=False)
        raise Problem(409, "Job is no longer active")

    def stop(self, room: str):
        with self.transaction():
            self.db.execute(
                "UPDATE runs SET status='stopped' WHERE room=? AND status='running'", (room,)
            )
            self.db.execute(
                "UPDATE jobs SET status='stopped' WHERE room=? AND status='pending'", (room,)
            )

    def phase(self, run: str) -> str:
        row = self.db.execute("SELECT lead,turn,budget FROM runs WHERE id=?", (run,)).fetchone()
        if row["lead"] and row["turn"] == 0:
            return "lead-plan"
        if row["lead"] and row["turn"] == row["budget"] - 1:
            return "lead-summary"
        return "contribute"

    def list_rooms(self) -> list:
        with self.lock:
            return [
                dict(r)
                for r in self.db.execute("SELECT id,name,lead FROM rooms ORDER BY rowid DESC")
            ]

    def registry(self) -> list:
        with self.lock:
            return [
                dict(r)
                for r in self.db.execute(
                    "SELECT *,CASE WHEN kind='demo' THEN 'demo-local' ELSE 'owner-setup-required' END AS availability FROM bots ORDER BY rowid"
                )
            ]

    def register_bot(self, aid: str, name: str, kind: str, description: str = "") -> dict:
        import re

        if (
            not isinstance(aid, str)
            or aid == "user"
            or not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", aid)
            or kind not in ("demo", "mailbox", "grok", "dot", "other-bot")
        ):
            raise Problem(400, "Invalid agent id or kind")
        text(name, 80)
        if not isinstance(description, str) or len(description) > 300:
            raise Problem(400, "Description must be at most 300 characters")
        with self.transaction():
            try:
                self.db.execute("INSERT INTO bots VALUES (?,?,?,?)", (aid, name, kind, description))
            except sqlite3.IntegrityError:
                raise Problem(409, "Bot already registered") from None
        return dict(id=aid, name=name, kind=kind, description=description)

    def idle(self, room: str):
        if self.db.execute(
            "SELECT 1 FROM runs WHERE room=? AND status='running'", (room,)
        ).fetchone():
            raise Problem(409, "Stop or finish the current run first")

    def join(self, room: str, aid: str) -> dict:
        with self.transaction():
            self.idle(room)
            bot = self.db.execute("SELECT * FROM bots WHERE id=?", (aid,)).fetchone()
            if not bot:
                raise Problem(404, "Registered bot not found")
            return self.add_agent(room, aid, bot["kind"])

    def settings(self, room: str, name: str, lead: str) -> dict:
        text(name, 80)
        if not isinstance(lead, str):
            raise Problem(400, "Invalid Lead")
        with self.transaction():
            self.idle(room)
            if (
                lead
                and not self.db.execute(
                    "SELECT 1 FROM agents WHERE room=? AND id=?", (room, lead)
                ).fetchone()
            ):
                raise Problem(400, "Lead must be a room participant")
            self.db.execute("UPDATE rooms SET name=?,lead=? WHERE id=?", (name, lead, room))
        return dict(id=room, name=name, lead=lead)

    def remove_agent(self, room: str, aid: str):
        with self.transaction():
            self.idle(room)
            self.handoffs.revoke(room, aid)
            self.db.execute("DELETE FROM agents WHERE room=? AND id=?", (room, aid))
            self.db.execute("UPDATE rooms SET lead='' WHERE id=? AND lead=?", (room, aid))

    def grant(self, room: str, aid: str, allowance: int) -> dict:
        if type(allowance) is not int or not 0 <= allowance <= 20:
            raise Problem(400, "Initiation allowance must be 0–20 total replies")
        with self.transaction():
            self.idle(room)
            if not self.db.execute(
                "SELECT 1 FROM agents WHERE room=? AND id=?", (room, aid)
            ).fetchone():
                raise Problem(404, "Agent not found")
            self.db.execute(
                "UPDATE agents SET allowance=? WHERE room=? AND id=?", (allowance, room, aid)
            )
        return dict(id=aid, allowance=allowance)

    def stop_peer(self, room: str, agent: str):
        with self.transaction():
            active = self.db.execute(
                "SELECT actor FROM runs WHERE room=? AND status='running'", (room,)
            ).fetchone()
            if active and active["actor"] != "bot:" + agent:
                raise Problem(403, "Cannot stop another identity's discussion")
            self.stop(room)

    def state(self, room: str, actor: str = "user") -> dict:
        self.expire()
        with self.lock:
            room_row = self.db.execute(
                "SELECT id,name,lead FROM rooms WHERE id=?", (room,)
            ).fetchone()
            if not room_row:
                raise Problem(404, "Room not found")
            return dict(
                room=dict(room_row),
                tasks=self.handoffs.listing(room, actor),
                agents=[
                    dict(r)
                    for r in self.db.execute(
                        "SELECT a.id,a.kind,a.allowance,COALESCE(b.name,a.id) AS name,COALESCE(b.description,'') AS description,CASE WHEN a.kind='demo' THEN 'demo-local' ELSE 'owner-setup-required' END AS availability FROM agents a LEFT JOIN bots b ON b.id=a.id WHERE a.room=? ORDER BY a.rowid",
                        (room,),
                    )
                ],
                runs=[
                    dict(r)
                    for r in self.db.execute(
                        "SELECT * FROM runs WHERE room=? ORDER BY rowid", (room,)
                    )
                ],
                messages=[
                    dict(r)
                    for r in self.db.execute(
                        "SELECT * FROM messages WHERE room=? ORDER BY id", (room,)
                    )
                ],
            )

    def demo_tick(self):
        self.expire()
        with self.lock:
            self.handoffs.demo_tick()
        with self.lock:
            agents = self.db.execute("SELECT room,id FROM agents WHERE kind='demo'").fetchall()
        for agent in agents:
            for job in self.inbox(agent["room"], agent["id"]):
                last = job["messages"][-1]["body"][:250]
                body = (
                    (
                        "[DEMO Lead] Plan within the approved participants and budget. "
                        if job["phase"] == "lead-plan"
                        else "[DEMO Lead] Summary of the bounded discussion. "
                        if job["phase"] == "lead-summary"
                        else ""
                    )
                    + (
                        "[DEMO planner] 建议把目标拆成可验证的小步骤。回应："
                        if agent["id"] == "demo-planner"
                        else "[DEMO critic] 请补充边界条件与验收证据。回应："
                    )
                    + last
                )
                try:
                    self.reply(agent["room"], agent["id"], job["id"], body)
                except Problem as exc:
                    if exc.status != 409:
                        raise
