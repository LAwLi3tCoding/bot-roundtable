"""Local-first bot room relay. Python 3.12+, standard library only."""

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
        # Never replay an uncertain external dispatch after a process restart.
        self.db.execute("UPDATE runs SET status='interrupted' WHERE status='running'")
        self.db.execute("UPDATE jobs SET status='interrupted' WHERE status='pending'")
        self.db.commit()

    @contextmanager
    def transaction(self):
        with self.lock, self.db:
            yield

    def room(self, name: str) -> dict:
        name = text(name, 80)
        rid, token = secrets.token_hex(12), secrets.token_urlsafe(32)
        with self.transaction():
            self.db.execute("INSERT INTO rooms VALUES (?,?,?)", (rid, digest(token), name))
            for aid in ("demo-planner", "demo-critic"):
                self.db.execute("INSERT INTO agents VALUES (?,?,?,?)", (rid, aid, "demo", ""))
        return dict(id=rid, token=token, name=name)

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
            or not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", aid)
            or kind not in ("mailbox", "grok")
        ):
            raise Problem(400, "Invalid agent id or kind")
        token = secrets.token_urlsafe(32)
        with self.transaction():
            try:
                self.db.execute(
                    "INSERT INTO agents VALUES (?,?,?,?)", (room, aid, kind, digest(token))
                )
            except sqlite3.IntegrityError:
                raise Problem(409, "Agent already exists") from None
        return dict(id=aid, token=token, kind=kind)

    def message(self, room: str, run: str, sender: str, source: str, body: str):
        self.db.execute(
            "INSERT INTO messages(room,run,sender,source,body,created) VALUES (?,?,?,?,?,?)",
            (room, run, sender, source, body, time.time()),
        )

    def start(self, room: str, body: str, targets: list, budget: int, request: str) -> dict:
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
            run = secrets.token_hex(12)
            self.db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,0,?)",
                (run, room, request, json.dumps(targets), budget, "running"),
            )
            self.message(room, run, "user", "human", body)
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

    def state(self, room: str) -> dict:
        self.expire()
        with self.lock:
            return dict(
                agents=[
                    dict(r)
                    for r in self.db.execute("SELECT id,kind FROM agents WHERE room=?", (room,))
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
            agents = self.db.execute("SELECT room,id FROM agents WHERE kind='demo'").fetchall()
        for agent in agents:
            for job in self.inbox(agent["room"], agent["id"]):
                last = job["messages"][-1]["body"][:250]
                body = (
                    "[DEMO planner] 建议把目标拆成可验证的小步骤。回应："
                    if agent["id"] == "demo-planner"
                    else "[DEMO critic] 请补充边界条件与验收证据。回应："
                ) + last
                try:
                    self.reply(agent["room"], agent["id"], job["id"], body)
                except Problem as exc:
                    if exc.status != 409:
                        raise
