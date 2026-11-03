"""Legacy room log and task notices. Wake-ups go only through mailboxes."""

import json
import os
import time


class Discussions:
    def __init__(self, store):
        self.store = store
        store.db.executescript("""
        CREATE TABLE IF NOT EXISTS discussion_messages(
          id INTEGER PRIMARY KEY, room TEXT, sender TEXT, body TEXT,
          mentions TEXT, reply_to INTEGER, depth INTEGER, created REAL,
          request TEXT, UNIQUE(room,sender,request));
        """)

        columns = {row[1] for row in store.db.execute("PRAGMA table_info(discussion_messages)")}
        for column in ("root", "task_id", "budget", "lead", "sender_epoch", "closed", "notice"):
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
        if kind not in ("delegated", "claimed", "progress", "completed", "failed", "cancelled"):
            return
        db = self.store.db
        row = db.execute("SELECT room,title FROM tasks WHERE id=?", (task,)).fetchone()
        worker = db.execute("SELECT worker FROM assignments WHERE id=?", (assignment,)).fetchone()
        mentions = [worker[0]] if kind == "delegated" and worker else []
        # Task bodies may contain credentials or private URLs; keep details in the scoped task.
        summary = ""
        notice = {
            "kind": kind,
            "actor": actor,
            "task_title": row["title"],
            "worker": worker[0] if worker else None,
            "summary": summary,
        }
        request = f"task:{event_id}:{task}"
        if kind == "progress":
            # Bound discussion noise; full progress remains in the task event log.
            request = f"progress:{task}:{assignment}:{int(time.time() // 60)}"
        db.execute(
            "INSERT OR IGNORE INTO discussion_messages(room,sender,body,mentions,reply_to,depth,created,request,task_id,notice) VALUES(?,?,?,?,NULL,0,?,?,?,?)",
            (
                row["room"],
                "system",
                summary,
                json.dumps(mentions),
                time.time(),
                request,
                task,
                json.dumps(notice),
            ),
        )

    @staticmethod
    def decode(row):
        result = dict(row)
        result["mentions"] = json.loads(result["mentions"])
        result["notice"] = json.loads(result["notice"]) if result.get("notice") else None
        result.pop("request", None)
        result.pop("sender_epoch", None)
        return result

    def listing(self, room):
        return [
            self.decode(row)
            for row in self.store.db.execute(
                "SELECT * FROM discussion_messages WHERE room=? ORDER BY id DESC LIMIT 100", (room,)
            )
        ][::-1]
