"""Scoped discussion messages; mention text never grants authority."""

import hashlib
import json
import logging
import os
import time
from roundtable import Problem, text


class Discussions:
    def __init__(self, store):
        self.store = store
        store.db.executescript("""
        CREATE TABLE IF NOT EXISTS discussion_messages(
          id INTEGER PRIMARY KEY, room TEXT, sender TEXT, body TEXT,
          mentions TEXT, reply_to INTEGER, depth INTEGER, created REAL,
          request TEXT, UNIQUE(room,sender,request));
        CREATE TABLE IF NOT EXISTS discussion_mentions(
          message INTEGER, room TEXT, bot TEXT, epoch TEXT,
          PRIMARY KEY(message,bot));
        """)

        columns = {row[1] for row in store.db.execute("PRAGMA table_info(discussion_messages)")}
        for column in ("root", "task_id", "budget", "lead", "sender_epoch", "closed"):
            if column not in columns:
                store.db.execute(f"ALTER TABLE discussion_messages ADD COLUMN {column} TEXT")
        store.db.commit()

    def active(self, room):
        return (
            self.store.db.execute(
                "SELECT 1 FROM discussion_messages r WHERE r.room=? AND r.sender='user' "
                "AND r.closed IS NULL AND r.root=CAST(r.id AS TEXT) AND "
                "(SELECT COUNT(*) FROM discussion_messages m WHERE m.room=r.room AND m.root=r.root "
                "AND m.sender LIKE 'bot:%') < CAST(COALESCE(r.budget,'4') AS INTEGER) LIMIT 1",
                (room,),
            ).fetchone()
            is not None
        )

    def close(self, room):
        self.store.db.execute(
            "UPDATE discussion_messages SET closed='stopped' WHERE room=? AND sender='user'",
            (room,),
        )

    def system_notice(self, task, assignment, actor, kind, body, event_id):
        if os.environ.get("ROUNDTABLE_TASK_NOTICES", "1") == "0":
            return
        if kind not in ("delegated", "claimed", "completed", "failed", "cancelled"):
            return
        db = self.store.db
        row = db.execute("SELECT room,title FROM tasks WHERE id=?", (task,)).fetchone()
        worker = db.execute("SELECT worker FROM assignments WHERE id=?", (assignment,)).fetchone()
        mentions = [worker[0]] if kind == "delegated" and worker else []
        summary = "\n".join(str(body).splitlines()[:2])[:400]
        content = f"{actor}: {kind}: {row['title']}" + ("\n" + summary if summary else "")
        db.execute(
            "INSERT INTO discussion_messages(room,sender,body,mentions,reply_to,depth,created,request,task_id) VALUES(?,?,?,?,NULL,0,?,?,?)",
            (
                row["room"],
                "system",
                content,
                json.dumps(mentions),
                time.time(),
                f"task:{event_id}:{task}",
                task,
            ),
        )

    @staticmethod
    def decode(row):
        result = dict(row)
        result["mentions"] = json.loads(result["mentions"])
        result.pop("request", None)
        result.pop("sender_epoch", None)
        return result

    def post(self, room, actor, data):
        body = text(data.get("body"))
        request = text(data.get("request_id"), 128)
        budget = data.get("budget", 4)
        if type(budget) is not int or not 1 <= budget <= 20:
            raise Problem(400, "Choose 1–20 total replies")
        mentions = data.get("mentions", [])
        if (
            not isinstance(mentions, list)
            or len(mentions) > 20
            or any(not isinstance(item, str) for item in mentions)
            or len(set(mentions)) != len(mentions)
        ):
            raise Problem(400, "Invalid mentions")
        reply = data.get("reply_to")
        if reply is not None and (type(reply) is not int or reply < 1):
            raise Problem(400, "Invalid reply reference")
        db = self.store.db
        with self.store.transaction():
            if actor != "user":
                member = db.execute(
                    "SELECT token FROM agents WHERE room=? AND id=?",
                    (room, actor.removeprefix("bot:")),
                ).fetchone()
                if not member:
                    raise Problem(403, "Room membership required")
                request = hashlib.sha256((member["token"] + ":" + request).encode()).hexdigest()
            old = db.execute(
                "SELECT * FROM discussion_messages WHERE room=? AND sender=? AND request=?",
                (room, actor, request),
            ).fetchone()
            if old:
                if (
                    old["body"] != body
                    or json.loads(old["mentions"]) != mentions
                    or old["reply_to"] != reply
                    or (actor == "user" and int(old["budget"] or 4) != budget)
                ):
                    raise Problem(409, "Conflicting message replay")
                return self.decode(old)
            if not db.execute("SELECT 1 FROM rooms WHERE id=?", (room,)).fetchone():
                raise Problem(404, "Room not found")
            if db.execute(
                "SELECT 1 FROM runs WHERE room=? AND status='running'", (room,)
            ).fetchone():
                raise Problem(
                    409, "Stop the orchestrated discussion before sending ordinary messages"
                )
            members = {r["id"]: r for r in db.execute("SELECT * FROM agents WHERE room=?", (room,))}
            if any(bot not in members for bot in mentions):
                raise Problem(400, "Mention must be a room member")
            bot = actor.removeprefix("bot:") if actor != "user" else None
            if bot and bot not in members:
                raise Problem(403, "Room membership required")
            parent = None
            if reply:
                parent = db.execute(
                    "SELECT * FROM discussion_messages WHERE room=? AND id=?", (room, reply)
                ).fetchone()
                if not parent:
                    raise Problem(404, "Reply message not found")
            # Bots cannot reset the chain by omitting a reference.
            root_row = None
            if bot and parent:
                root_row = db.execute(
                    "SELECT * FROM discussion_messages WHERE id=? AND room=?",
                    (parent["root"] or parent["id"], room),
                ).fetchone()
                if root_row["closed"]:
                    raise Problem(409, "Discussion was stopped")
                budget = int(root_row["budget"] or 4)
            depth = (parent["depth"] + 1 if parent else budget) if bot else 0
            root = str(parent["root"] or parent["id"]) if parent and bot else None
            used = 0
            if bot and root:
                used = db.execute(
                    "SELECT COUNT(*) FROM discussion_messages WHERE room=? AND root=? AND sender LIKE 'bot:%'",
                    (room, root),
                ).fetchone()[0]
                if used >= budget or depth > budget:
                    raise Problem(409, "Discussion reply budget exhausted")
            now = time.time()
            wakes = []
            for target in mentions if mentions or bot else list(members):
                recent = db.execute(
                    "SELECT COUNT(*) FROM discussion_mentions n JOIN discussion_messages m ON m.id=n.message WHERE n.bot=? AND m.created>?",
                    (target, now - 60),
                ).fetchone()[0]
                if (
                    depth >= budget
                    or (bot and root and used + 1 >= budget)
                    or target == bot
                    or recent >= 10
                ):
                    logging.info("discussion mention wake suppressed")
                else:
                    wakes.append(target)
            if bot and len(wakes) > members[bot]["allowance"]:
                raise Problem(403, "Bot initiation allowance exhausted")
            if bot:
                db.execute(
                    "UPDATE agents SET allowance=allowance-? WHERE room=? AND id=?",
                    (len(wakes), room, bot),
                )
            cursor = db.execute(
                "INSERT INTO discussion_messages(room,sender,body,mentions,reply_to,depth,created,request) VALUES(?,?,?,?,?,?,?,?)",
                (room, actor, body, json.dumps(mentions), reply, depth, now, request),
            )
            mid = cursor.lastrowid
            lead = db.execute("SELECT lead FROM rooms WHERE id=?", (room,)).fetchone()[0]
            db.execute(
                "UPDATE discussion_messages SET root=?,budget=?,lead=?,sender_epoch=? WHERE id=?",
                (
                    root or str(mid),
                    budget,
                    root_row["lead"] if root_row else lead,
                    members[bot]["token"] if bot else None,
                    mid,
                ),
            )
            for target in wakes:
                db.execute(
                    "INSERT INTO discussion_mentions VALUES(?,?,?,?)",
                    (mid, room, target, members[target]["token"]),
                )
            return self.decode(
                db.execute("SELECT * FROM discussion_messages WHERE id=?", (mid,)).fetchone()
            )

    def inbox(self, room, actor, data):
        after = data.get("after", 0)
        if type(after) is not int or after < 0:
            raise Problem(400, "Invalid cursor")
        bot = actor.removeprefix("bot:")
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT m.* FROM discussion_messages m JOIN discussion_mentions n ON n.message=m.id JOIN agents a ON a.room=n.room AND a.id=n.bot AND a.token=n.epoch WHERE n.room=? AND n.bot=? AND m.id>? AND NOT EXISTS (SELECT 1 FROM discussion_messages root WHERE CAST(root.id AS TEXT)=m.root AND root.closed IS NOT NULL) ORDER BY m.id LIMIT 100",
                (room, bot, after),
            ).fetchall()
            return {
                "messages": [self.decode(row) for row in rows],
                "next_cursor": rows[-1]["id"] if rows else after,
            }

    def listing(self, room):
        return [
            self.decode(row)
            for row in self.store.db.execute(
                "SELECT * FROM discussion_messages WHERE room=? ORDER BY id DESC LIMIT 100", (room,)
            )
        ][::-1]
