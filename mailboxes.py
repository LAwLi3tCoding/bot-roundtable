"""Recipient mailboxes. Topic membership grants full topic history; mentions only wake."""

import json
import secrets
import time

from roundtable import Problem, text


class Mailboxes:
    def __init__(self, store):
        self.store = store
        store.db.executescript("""
        CREATE TABLE IF NOT EXISTS mail_roundtables(room TEXT PRIMARY KEY, topic TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS mail_topics(id TEXT PRIMARY KEY, room TEXT NOT NULL,
          title TEXT NOT NULL, creator TEXT NOT NULL, request TEXT NOT NULL, initial_members TEXT NOT NULL,
          budget INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0, stopped INTEGER DEFAULT 0,
          UNIQUE(room,creator,request));
        CREATE TABLE IF NOT EXISTS mail_members(topic TEXT, actor TEXT, epoch TEXT NOT NULL, cursor INTEGER DEFAULT 0,
          PRIMARY KEY(topic,actor));
        CREATE TABLE IF NOT EXISTS mail_messages(id INTEGER PRIMARY KEY, topic TEXT NOT NULL,
          sender TEXT NOT NULL, body TEXT NOT NULL, recipients TEXT NOT NULL, mentions TEXT NOT NULL,
          request TEXT NOT NULL, created REAL NOT NULL, UNIQUE(topic,sender,request));
        CREATE TABLE IF NOT EXISTS mail_deliveries(message INTEGER, actor TEXT, epoch TEXT NOT NULL, wake INTEGER,
          PRIMARY KEY(message,actor));
        """)
        store.db.commit()

    def _actor(self, room, actor):
        if not self.store.db.execute("SELECT 1 FROM rooms WHERE id=?", (room,)).fetchone():
            raise Problem(404, "Room not found")
        if actor != "user" and (
            not actor.startswith("bot:")
            or not self.store.db.execute(
                "SELECT 1 FROM agents WHERE room=? AND id=?", (room, actor[4:])
            ).fetchone()
        ):
            raise Problem(403, "Room membership required")

    def _epoch(self, room, actor):
        if actor == "user":
            return "user"
        row = self.store.db.execute(
            "SELECT token FROM agents WHERE room=? AND id=?", (room, actor[4:])
        ).fetchone()
        return row[0] if row else None

    def _topic(self, room, actor, topic):
        self._actor(room, actor)
        row = self.store.db.execute(
            "SELECT * FROM mail_topics WHERE room=? AND id=?", (room, topic)
        ).fetchone()
        if not row or (
            actor != "user"
            and not self.store.db.execute(
                "SELECT 1 FROM mail_members WHERE topic=? AND actor=? AND epoch=?",
                (topic, actor, self._epoch(room, actor)),
            ).fetchone()
        ):
            raise Problem(404, "Topic not found")
        return row

    def _members(self, topic):
        return [
            r[0]
            for r in self.store.db.execute(
                "SELECT s.actor FROM mail_members s JOIN mail_topics t ON t.id=s.topic WHERE s.topic=? AND (s.actor='user' OR EXISTS(SELECT 1 FROM agents a WHERE a.room=t.room AND 'bot:'||a.id=s.actor AND a.token=s.epoch)) ORDER BY s.actor",
                (topic,),
            )
        ]

    @staticmethod
    def _decode(row):
        result = dict(row)
        result.pop("request", None)
        result.pop("initial_members", None)
        for key in ("recipients", "mentions"):
            result[key] = json.loads(result[key])
        return result

    def roundtable(self, room, actor="user"):
        """The shared workspace conversation; never adopt an existing private topic."""
        with self.store.transaction():
            self._actor(room, actor)
            db = self.store.db
            found = db.execute(
                "SELECT topic FROM mail_roundtables WHERE room=?", (room,)
            ).fetchone()
            if found:
                topic = found["topic"]
            else:
                topic = secrets.token_hex(12)
                db.execute(
                    "INSERT INTO mail_topics(id,room,title,creator,request,budget,initial_members) VALUES(?,?,?,?,?,?,?)",
                    (topic, room, "圆桌", "user", "roundtable:" + topic, 4, "[]"),
                )
                db.execute("INSERT INTO mail_roundtables VALUES(?,?)", (room, topic))
            members = ["user"] + [
                "bot:" + row["id"]
                for row in db.execute("SELECT id FROM agents WHERE room=? ORDER BY id", (room,))
            ]
            for member in members:
                db.execute(
                    "INSERT INTO mail_members(topic,actor,epoch) VALUES(?,?,?) ON CONFLICT(topic,actor) DO UPDATE SET cursor=CASE WHEN mail_members.epoch=excluded.epoch THEN mail_members.cursor ELSE 0 END,epoch=excluded.epoch",
                    (topic, member, self._epoch(room, member)),
                )
            result = dict(db.execute("SELECT * FROM mail_topics WHERE id=?", (topic,)).fetchone())
            result.pop("request", None)
            result.pop("initial_members", None)
            return result | {"members": members, "shared": True}

    def create(self, room, actor, data):
        if any(k in data for k in ("sender", "recipients")):
            raise Problem(400, "Sender and recipients are server controlled")
        request = text(data.get("request_id"), 128)
        title = text(data.get("title"), 120)
        members = data.get("members")
        budget = data.get("budget", 4)
        if (
            not isinstance(members, list)
            or not 1 <= len(members) <= 20
            or any(not isinstance(m, str) for m in members)
        ):
            raise Problem(400, "Invalid members")
        members = sorted(
            set(
                [m if m == "user" or m.startswith("bot:") else "bot:" + m for m in members]
                + [actor]
            )
        )
        if len(members) < 2 or type(budget) is not int or not 1 <= budget <= 20:
            raise Problem(400, "Choose at least two members and 1–20 replies")
        with self.store.transaction():
            self._actor(room, actor)
            for member in members:
                if (
                    member != "user"
                    and not self.store.db.execute(
                        "SELECT 1 FROM agents WHERE room=? AND id=?", (room, member[4:])
                    ).fetchone()
                ):
                    raise Problem(
                        400,
                        f"不认识成员 {member[4:]}，请填写本工作区的 Bot id，例如 bot:dot / Unknown workspace Bot id",
                    )
            db = self.store.db
            old = db.execute(
                "SELECT * FROM mail_topics WHERE room=? AND creator=? AND request=?",
                (room, actor, request),
            ).fetchone()
            if old:
                if (
                    old["title"] != title
                    or old["budget"] != budget
                    or json.loads(old["initial_members"]) != members
                ):
                    raise Problem(409, "Conflicting topic replay")
                self._topic(room, actor, old["id"])
                result = dict(old)
                result.pop("request", None)
                result.pop("initial_members", None)
                return result | {"members": self._members(result["id"])}
            if actor != "user":
                self.store.consume_allowance(room, actor[4:], 1)
            topic = secrets.token_hex(12)
            db.execute(
                "INSERT INTO mail_topics(id,room,title,creator,request,budget,initial_members) VALUES(?,?,?,?,?,?,?)",
                (topic, room, title, actor, request, budget, json.dumps(members)),
            )
            db.executemany(
                "INSERT INTO mail_members(topic,actor,epoch) VALUES(?,?,?)",
                [(topic, m, self._epoch(room, m)) for m in members],
            )
            result = dict(db.execute("SELECT * FROM mail_topics WHERE id=?", (topic,)).fetchone())
            result.pop("request", None)
            result.pop("initial_members", None)
            return result | {"members": self._members(result["id"])}

    def topics(self, room, actor):
        with self.store.lock:
            self._actor(room, actor)
            rows = self.store.db.execute(
                "SELECT * FROM mail_topics WHERE room=? ORDER BY rowid DESC", (room,)
            ).fetchall()
            result = []
            for row in rows:
                members = self._members(row["id"])
                if actor != "user" and actor not in members:
                    continue
                item = dict(row)
                item.pop("request", None)
                item.pop("initial_members", None)
                item["members"] = members
                last = self.store.db.execute(
                    "SELECT * FROM mail_messages WHERE topic=? ORDER BY id DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                item["last_message"] = self._decode(last) if last else None
                item["unread"] = self.store.db.execute(
                    "SELECT COUNT(*) FROM mail_deliveries d JOIN mail_messages m ON m.id=d.message JOIN mail_members s ON s.topic=m.topic AND s.actor=d.actor WHERE m.topic=? AND d.actor=? AND m.id>s.cursor AND d.epoch=s.epoch AND s.epoch=?",
                    (row["id"], actor, self._epoch(room, actor)),
                ).fetchone()[0]
                result.append(item)
            return result

    def messages(self, room, actor, topic, after=0):
        self._cursor(after)
        with self.store.lock:
            self._topic(room, actor, topic)
            rows = self.store.db.execute(
                "SELECT * FROM mail_messages WHERE topic=? AND id>? ORDER BY id LIMIT 100",
                (topic, after),
            ).fetchall()
            return {
                "messages": [self._decode(r) for r in rows],
                "next_cursor": rows[-1]["id"] if rows else after,
            }

    @staticmethod
    def _cursor(cursor):
        if type(cursor) is not int or cursor < 0:
            raise Problem(400, "Invalid cursor")

    def post(self, room, actor, topic, data):
        body = text(data.get("body"))
        request = text(data.get("request_id"), 128)
        mentions = data.get("mentions", [])
        if any(k in data for k in ("sender", "recipients")):
            raise Problem(400, "Sender and recipients are server controlled")
        if (
            not isinstance(mentions, list)
            or any(not isinstance(m, str) for m in mentions)
            or len(mentions) != len(set(mentions))
        ):
            raise Problem(400, "Invalid mentions")
        with self.store.transaction():
            row = self._topic(room, actor, topic)
            db = self.store.db
            old = db.execute(
                "SELECT * FROM mail_messages WHERE topic=? AND sender=? AND request=?",
                (topic, actor, request),
            ).fetchone()
            if old:
                if old["body"] != body or json.loads(old["mentions"]) != mentions:
                    raise Problem(409, "Conflicting message replay")
                return self._decode(old)
            members = self._members(topic)
            if actor not in members:
                if actor != "user" or data.get("join") is not True:
                    raise Problem(403, "Join the topic before replying")
                members.append(actor)
            recipients = sorted(m for m in members if m != actor)
            if any(m not in recipients or not m.startswith("bot:") for m in mentions):
                raise Problem(400, "Mention must be another bot in this topic")
            if row["stopped"]:
                raise Problem(409, "Topic stopped")
            if actor != "user" and row["used"] >= row["budget"]:
                raise Problem(409, "Reply budget exhausted")
            now = time.time()
            wakes = []
            for target in mentions:
                recent = db.execute(
                    "SELECT COUNT(*) FROM mail_deliveries d JOIN mail_messages m ON m.id=d.message JOIN mail_topics t ON t.id=m.topic WHERE t.room=? AND d.actor=? AND d.wake=1 AND m.created>?",
                    (room, target, now - 60),
                ).fetchone()[0]
                if recent < 10 and (actor == "user" or row["used"] + 1 < row["budget"]):
                    wakes.append(target)
            if actor != "user":
                self.store.consume_allowance(room, actor[4:], len(wakes))
                db.execute("UPDATE mail_topics SET used=used+1 WHERE id=?", (topic,))
            if actor == "user":
                db.execute("UPDATE mail_topics SET used=0 WHERE id=?", (topic,))
            db.execute(
                "INSERT OR IGNORE INTO mail_members(topic,actor,epoch) VALUES(?,?,?)",
                (topic, actor, self._epoch(room, actor)),
            )
            mid = db.execute(
                "INSERT INTO mail_messages(topic,sender,body,recipients,mentions,request,created) VALUES(?,?,?,?,?,?,?)",
                (topic, actor, body, json.dumps(recipients), json.dumps(mentions), request, now),
            ).lastrowid
            db.executemany(
                "INSERT INTO mail_deliveries VALUES(?,?,?,?)",
                [
                    (mid, target, self._epoch(room, target), int(target in wakes))
                    for target in recipients
                ],
            )
            return self._decode(
                db.execute("SELECT * FROM mail_messages WHERE id=?", (mid,)).fetchone()
            )

    def inbox(self, room, actor, after=0, wake_only=False):
        self._cursor(after)
        with self.store.lock:
            self._actor(room, actor)
            rows = self.store.db.execute(
                "SELECT m.*,d.wake FROM mail_messages m JOIN mail_topics t ON t.id=m.topic JOIN mail_deliveries d ON d.message=m.id JOIN mail_members s ON s.topic=t.id AND s.actor=d.actor WHERE t.room=? AND d.actor=? AND m.id>? AND s.epoch=? AND d.epoch=s.epoch AND (?=0 OR (d.wake=1 AND t.stopped=0)) ORDER BY m.id LIMIT 100",
                (room, actor, after, self._epoch(room, actor), int(wake_only)),
            ).fetchall()
            return {
                "messages": [self._decode(r) for r in rows],
                "next_cursor": rows[-1]["id"] if rows else after,
            }

    def wake_inbox(self, room, actor, after=0):
        return self.inbox(room, actor, after, wake_only=True)

    def active(self, room):
        return bool(
            self.store.db.execute(
                "SELECT 1 FROM mail_topics WHERE room=? AND stopped=0 AND used<budget", (room,)
            ).fetchone()
        )

    def close(self, room):
        self.store.db.execute("UPDATE mail_topics SET stopped=1 WHERE room=?", (room,))

    def read(self, room, actor, topic, cursor):
        self._cursor(cursor)
        with self.store.transaction():
            self._topic(room, actor, topic)
            maximum = self.store.db.execute(
                "SELECT COALESCE(MAX(id),0) FROM mail_messages WHERE topic=?", (topic,)
            ).fetchone()[0]
            if cursor > maximum:
                raise Problem(400, "Cursor exceeds topic history")
            self.store.db.execute(
                "UPDATE mail_members SET cursor=MAX(cursor,?) WHERE topic=? AND actor=?",
                (cursor, topic, actor),
            )
            return {"ok": True}

    def update(self, room, actor, topic, data):
        if actor != "user":
            raise Problem(403, "只有你可以修改对话 / Only you can edit this conversation")
        with self.store.transaction():
            row = self._topic(room, actor, topic)
            title = text(data.get("title", row["title"]), 120)
            members = data.get("members", self._members(topic))
            if (
                not isinstance(members, list)
                or not 2 <= len(members) <= 20
                or any(not isinstance(m, str) for m in members)
            ):
                raise Problem(400, "请选择 2–20 位成员 / Choose 2–20 members")
            members = sorted(
                set(m if m == "user" or m.startswith("bot:") else "bot:" + m for m in members)
            )
            if len(members) < 2:
                raise Problem(400, "请选择至少两位不同成员 / Choose two distinct members")
            for member in members:
                if (
                    member != "user"
                    and not self.store.db.execute(
                        "SELECT 1 FROM agents WHERE room=? AND id=?", (room, member[4:])
                    ).fetchone()
                ):
                    raise Problem(
                        400,
                        f"不认识成员 {member[4:]}，请填写本工作区的 Bot id，例如 bot:dot / Unknown workspace Bot id",
                    )
            db = self.store.db
            db.execute("UPDATE mail_topics SET title=? WHERE id=?", (title, topic))
            for previous in self._members(topic):
                if previous not in members:
                    db.execute(
                        "DELETE FROM mail_members WHERE topic=? AND actor=?", (topic, previous)
                    )
            for member in members:
                epoch = self._epoch(room, member)
                db.execute(
                    "INSERT INTO mail_members(topic,actor,epoch) VALUES(?,?,?) ON CONFLICT(topic,actor) DO UPDATE SET cursor=CASE WHEN mail_members.epoch=excluded.epoch THEN mail_members.cursor ELSE 0 END,epoch=excluded.epoch",
                    (topic, member, epoch),
                )
            return {"id": topic, "title": title, "members": members}

    def stop(self, room, actor, topic):
        with self.store.transaction():
            row = self._topic(room, actor, topic)
            if actor != "user" and actor != row["creator"]:
                raise Problem(403, "Only owner or creator may stop a topic")
            self.store.db.execute("UPDATE mail_topics SET stopped=1 WHERE id=?", (topic,))
            return {"ok": True}
