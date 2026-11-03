"""Durable independent assignments. No tools, network dispatch, or provider execution."""

import json
import secrets
import time

from roundtable import Problem, digest, text

TERMINAL = {"completed", "failed", "cancelled", "timeout", "revoked"}


NOTIFICATION_EVENT = "roundtable.notification"
NOTIFICATION_KINDS = ("task.assigned", "task.updated", "task.finished", "message")
TASK_FINISHED = {
    "task_completed": "completed",
    "task_failed": "failed",
    "task_timeout": "timeout",
    "cancelled": "cancelled",
}
_CURSOR_SHIFT = 2**31


def pack_cursor(task_position, message_position):
    """One opaque integer cursor for the broker; both positions stay below 2**31."""
    if not (0 <= task_position < _CURSOR_SHIFT and 0 <= message_position < _CURSOR_SHIFT):
        raise Problem(500, "Event cursor overflow")
    return task_position * _CURSOR_SHIFT + message_position


def unpack_cursor(cursor):
    return divmod(cursor, _CURSOR_SHIFT)


class Handoffs:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks(
          id TEXT PRIMARY KEY, room TEXT NOT NULL, origin TEXT NOT NULL, origin_epoch TEXT,
          coordinator TEXT NOT NULL, title TEXT, context TEXT, parent TEXT, root TEXT,
          depth INTEGER, budget INTEGER, used INTEGER, status TEXT, deadline REAL, created REAL);
        CREATE TABLE IF NOT EXISTS assignments(
          id TEXT PRIMARY KEY, task TEXT NOT NULL, worker TEXT NOT NULL, epoch TEXT,
          instruction TEXT, status TEXT, attempt INTEGER, lease_hash TEXT, lease_until REAL,
          result TEXT, artifacts TEXT, UNIQUE(task,worker));
        CREATE TABLE IF NOT EXISTS task_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, assignment TEXT, actor TEXT,
          kind TEXT, body TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS task_receipts(
          room TEXT, actor TEXT, operation TEXT, nonce TEXT, fingerprint TEXT, response TEXT,
          PRIMARY KEY(room,actor,operation,nonce));
        CREATE TABLE IF NOT EXISTS event_namespace(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS task_room_idx ON tasks(room,created);
        CREATE INDEX IF NOT EXISTS assignment_worker_idx ON assignments(worker,task);
        CREATE INDEX IF NOT EXISTS task_event_idx ON task_events(task,id);
        """)
        if "topic_id" not in {row[1] for row in self.db.execute("PRAGMA table_info(tasks)")}:
            self.db.execute("ALTER TABLE tasks ADD COLUMN topic_id TEXT")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(assignments)")}
        if "lease_seconds" not in columns:
            self.db.execute(
                "ALTER TABLE assignments ADD COLUMN lease_seconds INTEGER NOT NULL DEFAULT 60"
            )
        self.db.execute(
            "INSERT OR IGNORE INTO event_namespace VALUES(1,?)", (secrets.token_hex(16),)
        )
        self.event_namespace = self.db.execute(
            "SELECT value FROM event_namespace WHERE id=1"
        ).fetchone()[0]
        # Persist in-flight leases across restart; never auto-replay external work.
        self.db.commit()

    def member(self, room, actor):
        if not self.db.execute("SELECT 1 FROM rooms WHERE id=?", (room,)).fetchone():
            raise Problem(404, "Room not found")
        if actor == "user":
            return ""
        if not isinstance(actor, str) or not actor.startswith("bot:"):
            raise Problem(403, "Task identity required")
        self.store.require_active_bot(room, actor[4:])
        row = self.db.execute(
            "SELECT token FROM agents WHERE room=? AND id=?", (room, actor[4:])
        ).fetchone()
        if not row:
            raise Problem(403, "Task identity required")
        return row["token"]

    def task(self, room, actor, tid):
        epoch = self.member(room, actor)
        row = self.db.execute("SELECT * FROM tasks WHERE room=? AND id=?", (room, tid)).fetchone()
        if not row:
            raise Problem(404, "Task not found")
        origin = actor == row["origin"] and epoch == row["origin_epoch"]
        worker = (
            actor.startswith("bot:")
            and self.db.execute(
                "SELECT 1 FROM assignments WHERE task=? AND worker=? AND epoch=?",
                (tid, actor[4:], epoch),
            ).fetchone()
        )
        if actor != "user" and not origin and not worker:
            raise Problem(403, "Task scope denied")
        return dict(row)

    def control(self, task, actor):
        if actor not in ("user", task["origin"]):
            raise Problem(403, "Only task origin or room owner may coordinate")

    def event(self, tid, aid, actor, kind, body):
        inserted = self.db.execute(
            "INSERT INTO task_events(task,assignment,actor,kind,body,created) VALUES(?,?,?,?,?,?)",
            (tid, aid, actor, kind, body, time.time()),
        )
        discussions = getattr(self.store, "discussions", None)
        if discussions is not None:
            discussions.system_notice(tid, aid, actor, kind, body, inserted.lastrowid)

    def receipt(self, room, actor, operation, nonce, payload, apply):
        text(nonce, 100)
        actor_key = actor + ":" + self.member(room, actor)
        fingerprint = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        row = self.db.execute(
            "SELECT * FROM task_receipts WHERE room=? AND actor=? AND operation=? AND nonce=?",
            (room, actor_key, operation, nonce),
        ).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise Problem(409, "Idempotency key conflicts with original payload")
            return json.loads(row["response"])
        result = apply()
        self.db.execute(
            "INSERT INTO task_receipts VALUES(?,?,?,?,?,?)",
            (room, actor_key, operation, nonce, fingerprint, json.dumps(result)),
        )
        return result

    def settle(self, tid):
        task = self.db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()
        if not task or task["status"] in ("cancelled", "timeout"):
            return
        states = [
            r[0] for r in self.db.execute("SELECT status FROM assignments WHERE task=?", (tid,))
        ]
        status = (
            "running"
            if any(s not in TERMINAL for s in states)
            else "completed"
            if all(s == "completed" for s in states)
            else "failed"
        )
        if status != task["status"]:
            self.db.execute("UPDATE tasks SET status=? WHERE id=?", (status, tid))
            self.event(tid, "", "system", "task_" + status, "")

    def expire(self):
        now = time.time()
        with self.store.transaction():
            for row in self.db.execute(
                "SELECT * FROM tasks WHERE status='running' AND deadline<=?", (now,)
            ).fetchall():
                self.db.execute(
                    "UPDATE assignments SET status='timeout',lease_hash='',lease_until=0 WHERE task=? AND status IN ('queued','working')",
                    (row["id"],),
                )
                self.db.execute("UPDATE tasks SET status='timeout' WHERE id=?", (row["id"],))
                self.event(row["id"], "", "system", "task_timeout", "")
            for row in self.db.execute(
                "SELECT a.* FROM assignments a JOIN tasks t ON t.id=a.task WHERE a.status='working' AND a.lease_until<=? AND t.status='running'",
                (now,),
            ).fetchall():
                root = self.db.execute(
                    "SELECT r.budget,r.used FROM tasks t JOIN tasks r ON r.id=t.root WHERE t.id=?",
                    (row["task"],),
                ).fetchone()
                status = (
                    "queued" if row["attempt"] < 3 and root["used"] < root["budget"] else "failed"
                )
                self.db.execute(
                    "UPDATE assignments SET status=?,lease_hash='',lease_until=0 WHERE id=?",
                    (status, row["id"]),
                )
                self.event(row["task"], row["id"], "system", "lease_expired", status)
                self.settle(row["task"])

    def create(self, room, actor, data):
        title, context = text(data.get("title"), 120), text(data.get("context"))
        specs = data.get("assignments")
        parent = data.get("parent_task_id", "")
        topic_id = data.get("topic_id", "")
        if not isinstance(topic_id, str) or len(topic_id) > 40:
            raise Problem(400, "Invalid topic")
        budget, seconds = data.get("budget", 6), data.get("timeout_seconds", 600)
        if (
            type(budget) is not int
            or not 1 <= budget <= 20
            or type(seconds) is not int
            or not 30 <= seconds <= 86400
        ):
            raise Problem(400, "Task budget must be 1–20 and timeout 30–86400 seconds")
        if not isinstance(parent, str) or len(parent) > 40:
            raise Problem(400, "Invalid parent task")
        if not isinstance(specs, list) or not 1 <= len(specs) <= 6:
            raise Problem(400, "Choose 1–6 independent assignments")
        normalized = []
        for spec in specs:
            if not isinstance(spec, dict) or set(spec) != {"worker", "instruction"}:
                raise Problem(400, "Each assignment needs worker and instruction")
            normalized.append(
                dict(worker=text(spec["worker"], 40), instruction=text(spec["instruction"]))
            )
        workers = [s["worker"] for s in normalized]
        if len(set(workers)) != len(workers) or actor in ["bot:" + w for w in workers]:
            raise Problem(400, "Choose distinct workers other than the coordinator")
        payload: dict = dict(
            title=title,
            context=context,
            assignments=normalized,
            parent=parent,
            budget=budget,
            timeout=seconds,
        )
        if topic_id:
            payload["topic_id"] = topic_id
        self.expire()
        with self.store.transaction():
            epoch = self.member(room, actor)
            if topic_id:
                self.store.mailboxes._topic(room, actor, topic_id)
                members = self.store.mailboxes._members(topic_id)
                if actor not in members or any("bot:" + w not in members for w in workers):
                    raise Problem(400, "Task participants must belong to the conversation")
            if parent:
                p = self.task(room, actor, parent)
                self.control(p, actor)

            def apply():
                tid, now = secrets.token_hex(12), time.time()
                root, depth, deadline = tid, 0, now + seconds
                if parent:
                    p = self.task(room, actor, parent)
                    if (
                        p["origin"] != actor
                        or p["status"] != "running"
                        or p["deadline"] <= now
                        or p["depth"] >= 2
                    ):
                        raise Problem(
                            409, "Parent must be active with same origin and depth below 2"
                        )
                    root, depth, deadline = p["root"], p["depth"] + 1, min(deadline, p["deadline"])
                    root_row = self.db.execute("SELECT * FROM tasks WHERE id=?", (root,)).fetchone()
                    budget = root_row["budget"]
                    if (
                        root_row["status"] != "running"
                        or root_row["deadline"] <= now
                        or root_row["used"] + len(specs) > budget
                    ):
                        raise Problem(409, "Task dispatch budget exhausted")
                else:
                    budget = int(payload["budget"])
                    if len(specs) > budget:
                        raise Problem(400, "Task budget is smaller than assignment count")
                if (
                    self.db.execute(
                        "SELECT COUNT(*) FROM tasks WHERE room=? AND status='running'", (room,)
                    ).fetchone()[0]
                    >= 20
                ):
                    raise Problem(409, "Room active task limit reached")
                epochs = {}
                for worker in workers:
                    self.store.require_active_bot(room, worker)
                    row = self.db.execute(
                        "SELECT token FROM agents WHERE room=? AND id=?", (room, worker)
                    ).fetchone()
                    if not row:
                        raise Problem(403, "Worker is not a room member")
                    epochs[worker] = row["token"]
                if actor != "user":
                    self.store.consume_allowance(room, actor[4:], len(specs))
                self.db.execute(
                    "INSERT INTO tasks(id,room,origin,origin_epoch,coordinator,title,context,parent,root,depth,budget,used,status,deadline,created,topic_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        tid,
                        room,
                        actor,
                        epoch,
                        actor,
                        title,
                        context,
                        parent,
                        root,
                        depth,
                        budget,
                        len(specs) if not parent else 0,
                        "running",
                        deadline,
                        now,
                        self.task_topic(room, actor, topic_id),
                    ),
                )
                if parent:
                    self.db.execute("UPDATE tasks SET used=used+? WHERE id=?", (len(specs), root))
                self.event(tid, "", actor, "task_created", context)
                for spec in normalized:
                    aid = secrets.token_hex(12)
                    self.db.execute(
                        "INSERT INTO assignments(id,task,worker,epoch,instruction,status,attempt,lease_hash,lease_until,result,artifacts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            aid,
                            tid,
                            spec["worker"],
                            epochs[spec["worker"]],
                            spec["instruction"],
                            "queued",
                            0,
                            "",
                            0,
                            "",
                            "[]",
                        ),
                    )
                    self.event(tid, aid, actor, "delegated", spec["instruction"])
                return {
                    "task_id": tid,
                    "origin": actor,
                    "coordinator": actor,
                    "return_mode": "active-origin-poll",
                }

            return self.receipt(room, actor, "create", data.get("request_id"), payload, apply)

    def task_topic(self, room, actor, topic_id):
        if topic_id:
            return topic_id
        return self.store.mailboxes.roundtable(room, actor)["id"]

    def snapshot(self, room, actor, tid, after=0):
        if type(after) is not int or after < 0:
            raise Problem(400, "Invalid event cursor")
        self.expire()
        with self.store.transaction():
            task = self.task(room, actor, tid)
            rows = self.db.execute(
                "SELECT * FROM assignments WHERE task=? ORDER BY rowid", (tid,)
            ).fetchall()
            if not task["topic_id"]:
                # Never link old task history to a replacement Bot identity.
                valid = (
                    task["origin"] == "user"
                    or self.db.execute(
                        "SELECT 1 FROM agents WHERE room=? AND id=? AND token=?",
                        (room, task["origin"][4:], task["origin_epoch"]),
                    ).fetchone()
                )
                valid = valid and all(
                    self.db.execute(
                        "SELECT 1 FROM agents WHERE room=? AND id=? AND token=?",
                        (room, row["worker"], row["epoch"]),
                    ).fetchone()
                    for row in rows
                )
                if valid:
                    task["topic_id"] = self.task_topic(room, task["origin"], "")
                    self.db.execute(
                        "UPDATE tasks SET topic_id=? WHERE id=?", (task["topic_id"], tid)
                    )
            coordinator = actor in ("user", task["origin"])
            permitted = [r for r in rows if coordinator or r["worker"] == actor[4:]]
            assignments = [
                {
                    k: r[k]
                    for k in (
                        "id",
                        "worker",
                        "instruction",
                        "status",
                        "attempt",
                        "lease_until",
                        "result",
                    )
                }
                | {"artifacts": json.loads(r["artifacts"])}
                for r in permitted
            ]
            allowed = {r["id"] for r in permitted}
            events = [
                dict(r)
                for r in self.db.execute(
                    "SELECT * FROM task_events WHERE task=? AND id>? ORDER BY id", (tid, after)
                )
                if not r["assignment"] or r["assignment"] in allowed
            ][:101]
            has_more = len(events) > 100
            events = events[:100]
            task.pop("origin_epoch")
            task["updated"] = self.db.execute(
                "SELECT COALESCE(MAX(created),?) FROM task_events WHERE task=?",
                (task["created"], tid),
            ).fetchone()[0]
            root = self.db.execute(
                "SELECT budget,used FROM tasks WHERE id=?", (task["root"],)
            ).fetchone()
            return dict(
                task=task,
                assignments=assignments,
                events=events,
                cursor=events[-1]["id"] if events else after,
                has_more=has_more,
                budget={"limit": root["budget"], "used": root["used"]},
                return_mode="active-origin-poll",
            )

    def listing(self, room, actor):
        self.expire()
        with self.store.lock:
            self.member(room, actor)
            result = []
            for row in self.db.execute(
                "SELECT id FROM tasks WHERE room=? ORDER BY created DESC LIMIT 100", (room,)
            ).fetchall():
                try:
                    snap = self.snapshot(room, actor, row["id"])
                except Problem as exc:
                    if exc.status == 403:
                        continue
                    raise
                # Lists carry bounded previews, not every instruction/result/artifact.
                # Full payloads belong to get_task and its paginated event stream.
                task = {
                    k: snap["task"][k]
                    for k in (
                        "id",
                        "origin",
                        "coordinator",
                        "title",
                        "status",
                        "created",
                        "deadline",
                        "topic_id",
                        "updated",
                    )
                }
                task["context"] = snap["task"]["context"][:220]
                assignments = [
                    {k: a[k] for k in ("id", "worker", "status", "attempt")}
                    for a in snap["assignments"]
                ]
                result.append({"task": task, "assignments": assignments})
            return result

    def event_feed(self, room, actor, data):
        """Internal cursor feed for signed webhook delivery; not MCP event polling.

        One generic event, roundtable.notification. Payloads carry only kind, id and
        an optional status; bodies stay in the scoped inbox. The cursor packs the task
        event and discussion message positions into one opaque integer.
        """
        from datetime import datetime, timezone

        name, arguments, after = data.get("name"), data.get("arguments"), data.get("after")
        if name != NOTIFICATION_EVENT or arguments != {}:
            raise Problem(400, "Invalid event subscription")
        if after is not None and (type(after) is not int or after < 0):
            raise Problem(400, "Invalid event cursor")
        self.expire()
        with self.store.lock:
            epoch = self.member(room, actor)
            if actor == "user":
                raise Problem(403, "Worker identity required")
            if after is None:
                task_latest = self.db.execute(
                    "SELECT COALESCE(MAX(id),0) FROM task_events"
                ).fetchone()[0]
                message_latest = (
                    self.db.execute("SELECT COALESCE(MAX(id),0) FROM mail_messages").fetchone()[0]
                    if getattr(self.store, "mailboxes", None) is not None
                    else 0
                )
                return {"cursor": pack_cursor(task_latest, message_latest), "events": []}
            task_after, message_after = unpack_cursor(after)

            def stamp(created):
                return datetime.fromtimestamp(created, timezone.utc).isoformat()

            rows = self.db.execute(
                "SELECT e.* FROM task_events e JOIN tasks t ON t.id=e.task "
                "WHERE t.room=? AND e.id>? ORDER BY e.id LIMIT 100",
                (room, task_after),
            ).fetchall()
            result = []
            for row in rows:
                try:
                    task = self.task(room, actor, row["task"])
                except Problem as exc:
                    if exc.status == 403:
                        continue
                    raise
                assignment = self.db.execute(
                    "SELECT * FROM assignments WHERE id=? AND task=?",
                    (row["assignment"], row["task"]),
                ).fetchone()
                own = (
                    assignment
                    and assignment["worker"] == actor[4:]
                    and assignment["epoch"] == epoch
                )
                payload = None
                if (
                    own
                    and row["kind"] in ("delegated", "retry_requested", "lease_expired")
                    and assignment["status"] == "queued"
                    and task["status"] == "running"
                ):
                    payload = {"kind": "task.assigned", "id": row["task"]}
                elif (
                    task["origin"] == actor
                    and row["actor"] != actor
                    and row["kind"] not in ("task_created", "delegated", "task_running")
                ):
                    if row["kind"] in TASK_FINISHED:
                        payload = {
                            "kind": "task.finished",
                            "id": row["task"],
                            "status": TASK_FINISHED[row["kind"]],
                        }
                    else:
                        payload = {"kind": "task.updated", "id": row["task"], "status": row["kind"]}
                if payload is None:
                    continue
                result.append(
                    {
                        "eventId": f"evt_{self.event_namespace}_{row['id']}",
                        "name": NOTIFICATION_EVENT,
                        "timestamp": stamp(row["created"]),
                        "data": payload,
                        "cursor": None,
                    }
                )
            discussions = getattr(self.store, "mailboxes", None)
            page = (
                discussions.wake_inbox(room, actor, message_after)
                if discussions is not None
                else {"messages": [], "next_cursor": message_after}
            )
            for message in page["messages"]:
                result.append(
                    {
                        "eventId": f"message_{self.event_namespace}_{message['id']}",
                        "name": NOTIFICATION_EVENT,
                        "timestamp": stamp(message["created"]),
                        "data": {"kind": "message", "id": str(message["id"])},
                        "cursor": None,
                    }
                )
            return {
                "cursor": pack_cursor(rows[-1]["id"] if rows else task_after, page["next_cursor"]),
                "events": result,
            }

    def inbox(self, room, actor):
        if actor == "user":
            raise Problem(403, "Worker identity required")
        self.expire()
        with self.store.lock:
            epoch = self.member(room, actor)
            # Pending work must not disappear behind the history listing's
            # last-100 cap. Filter scope and state before selecting tasks.
            task_ids = self.db.execute(
                "SELECT t.id FROM tasks t JOIN assignments a ON a.task=t.id "
                "WHERE t.room=? AND t.status='running' AND a.worker=? AND a.epoch=? "
                "AND a.status IN ('queued','working') ORDER BY t.created",
                (room, actor[4:], epoch),
            ).fetchall()
            result = []
            for row in task_ids:
                snapshot = self.snapshot(room, actor, row["id"])
                for assignment in snapshot["assignments"]:
                    if assignment["worker"] == actor[4:] and assignment["status"] in (
                        "queued",
                        "working",
                    ):
                        result.append(
                            dict(
                                task_id=snapshot["task"]["id"],
                                origin=snapshot["task"]["origin"],
                                title=snapshot["task"]["title"],
                                deadline=snapshot["task"]["deadline"],
                                context=snapshot["task"]["context"],
                                **assignment,
                            )
                        )
            return result

    def operate(self, room, actor, operation, data):
        self.expire()
        tid = data.get("task_id")
        with self.store.transaction():
            task = self.task(room, actor, tid)
            aid = data.get("assignment_id", "")
            assignment = (
                self.db.execute(
                    "SELECT * FROM assignments WHERE task=? AND id=?", (tid, aid)
                ).fetchone()
                if aid
                else None
            )
            if operation in ("claim", "update"):
                if (
                    actor == "user"
                    or not assignment
                    or assignment["worker"] != actor[4:]
                    or assignment["epoch"] != self.member(room, actor)
                ):
                    raise Problem(403, "Only the assigned worker may claim or report")
            else:
                self.control(task, actor)
            payload = {k: v for k, v in data.items() if k != "request_id"}

            def apply():
                current = dict(assignment) if assignment else None
                now = time.time()
                if operation == "context":
                    body = text(data.get("body"))
                    if aid and not current:
                        raise Problem(404, "Assignment not found")
                    if (
                        self.db.execute(
                            "SELECT COUNT(*) FROM task_events WHERE task=? AND kind='context'",
                            (tid,),
                        ).fetchone()[0]
                        >= 100
                    ):
                        raise Problem(409, "Task context limit reached")
                    self.event(tid, aid, actor, "context", body)
                    return {"task_id": tid, "added": True}
                if operation == "cancel":
                    reason = data.get("reason")
                    reason = "" if reason is None else text(reason, 500)
                    targets = self.db.execute(
                        "WITH RECURSIVE subtree(id) AS ("
                        "SELECT id FROM tasks WHERE room=? AND id=? "
                        "UNION SELECT t.id FROM tasks t JOIN subtree s ON t.parent=s.id "
                        "WHERE t.room=?) SELECT id FROM subtree",
                        (room, tid, room),
                    ).fetchall()
                    for target in targets:
                        target_id = target["id"]
                        self.db.execute(
                            "UPDATE assignments SET status='cancelled',lease_hash='',lease_until=0 WHERE task=? AND status IN ('queued','working')",
                            (target_id,),
                        )
                        self.db.execute(
                            "UPDATE tasks SET status='cancelled' WHERE id=? AND status IN ('running','failed')",
                            (target_id,),
                        )
                        self.event(
                            target_id, "", actor, "cancelled", reason if target_id == tid else ""
                        )
                    return {"task_id": tid, "cancelled": True}
                if task["deadline"] <= now or task["status"] in ("cancelled", "timeout"):
                    raise Problem(409, "Task is closed")
                if not current:
                    raise Problem(404, "Assignment not found")
                if operation == "retry":
                    if current["status"] != "failed" or current["attempt"] >= 3:
                        raise Problem(
                            409, "Only failed assignments with attempts remaining can retry"
                        )
                    root = self.db.execute(
                        "SELECT budget,used FROM tasks WHERE id=?", (task["root"],)
                    ).fetchone()
                    if root["used"] >= root["budget"]:
                        raise Problem(409, "Task dispatch budget exhausted")
                    member = self.db.execute(
                        "SELECT token FROM agents WHERE room=? AND id=?",
                        (room, current["worker"]),
                    ).fetchone()
                    if not member or member["token"] != current["epoch"]:
                        raise Problem(403, "Original worker membership is no longer authorized")
                    if task["origin"] != "user":
                        self.store.refresh_allowances(room)
                        origin = self.db.execute(
                            "SELECT allowance,token FROM agents WHERE room=? AND id=?",
                            (room, task["origin"][4:]),
                        ).fetchone()
                        if (
                            not origin
                            or origin["token"] != task["origin_epoch"]
                            or origin["allowance"] < 1
                        ):
                            raise Problem(403, "Bot initiation allowance exhausted or not granted")
                    self.db.execute(
                        "UPDATE assignments SET status='queued',result='',artifacts='[]',lease_hash='',lease_until=0 WHERE id=?",
                        (aid,),
                    )
                    self.settle(tid)
                    self.event(tid, aid, actor, "retry_requested", "")
                    return {"assignment_id": aid, "status": "queued"}
                if operation == "claim":
                    lease_seconds = data.get("lease_seconds", 60)
                    if type(lease_seconds) is not int or not 30 <= lease_seconds <= 1800:
                        raise Problem(400, "Lease must be 30–1800 seconds")
                    if (
                        current["status"] != "queued"
                        or type(data.get("expected_attempt")) is not int
                        or data["expected_attempt"] != current["attempt"]
                    ):
                        raise Problem(409, "Assignment is not claimable at this attempt")
                    if current["attempt"] >= 3:
                        raise Problem(409, "Assignment attempt limit reached")
                    if current["attempt"]:
                        root = self.db.execute(
                            "SELECT budget,used FROM tasks WHERE id=?", (task["root"],)
                        ).fetchone()
                        if root["used"] >= root["budget"]:
                            raise Problem(409, "Task dispatch budget exhausted")
                        if task["origin"] != "user":
                            self.store.refresh_allowances(room)
                            origin = self.db.execute(
                                "SELECT allowance,token FROM agents WHERE room=? AND id=?",
                                (room, task["origin"][4:]),
                            ).fetchone()
                            if (
                                not origin
                                or origin["token"] != task["origin_epoch"]
                                or origin["allowance"] < 1
                            ):
                                raise Problem(
                                    403, "Bot initiation allowance exhausted or not granted"
                                )
                            self.store.consume_allowance(room, task["origin"][4:], 1)
                        self.db.execute("UPDATE tasks SET used=used+1 WHERE id=?", (task["root"],))
                    lease = secrets.token_urlsafe(32)
                    until = min(now + lease_seconds, task["deadline"])
                    self.db.execute(
                        "UPDATE assignments SET status='working',attempt=attempt+1,lease_hash=?,lease_until=?,lease_seconds=? WHERE id=?",
                        (digest(lease), until, lease_seconds, aid),
                    )
                    self.event(tid, aid, actor, "claimed", "")
                    return dict(
                        task_id=tid,
                        assignment_id=aid,
                        lease=lease,
                        attempt=current["attempt"] + 1,
                        lease_until=until,
                    )
                if operation != "update":
                    raise Problem(404, "Unknown task operation")
                if (
                    current["status"] != "working"
                    or current["lease_until"] <= now
                    or not isinstance(data.get("lease"), str)
                    or digest(data["lease"]) != current["lease_hash"]
                    or type(data.get("attempt")) is not int
                    or data.get("attempt") != current["attempt"]
                ):
                    raise Problem(409, "Lease is stale or assignment is closed")
                kind, body = data.get("kind"), text(data.get("body"))
                if kind not in ("progress", "completed", "failed"):
                    raise Problem(400, "Report kind must be progress, completed or failed")
                artifacts = data.get("artifacts", [])
                if (
                    not isinstance(artifacts, list)
                    or len(artifacts) > 3
                    or any(not isinstance(a, dict) or set(a) != {"name", "text"} for a in artifacts)
                ):
                    raise Problem(400, "Artifacts must be up to 3 named text results")
                for a in artifacts:
                    text(a["name"], 80)
                    text(a["text"], 2000)
                if (
                    self.db.execute(
                        "SELECT COUNT(*) FROM task_events WHERE task=? AND assignment=?", (tid, aid)
                    ).fetchone()[0]
                    >= 60
                    and kind == "progress"
                ):
                    raise Problem(409, "Assignment progress limit reached")
                until = (
                    min(now + current["lease_seconds"], task["deadline"])
                    if kind == "progress"
                    else 0
                )
                status = "working" if kind == "progress" else kind
                self.db.execute(
                    "UPDATE assignments SET status=?,lease_until=?,result=?,artifacts=? WHERE id=?",
                    (
                        status,
                        until,
                        body if kind != "progress" else current["result"],
                        json.dumps(artifacts) if kind != "progress" else current["artifacts"],
                        aid,
                    ),
                )
                self.event(tid, aid, actor, kind, body)
                self.settle(tid)
                return dict(task_id=tid, assignment_id=aid, status=status, lease_until=until)

            return self.receipt(room, actor, operation, data.get("request_id"), payload, apply)

    def revoke(self, room, aid):
        with self.store.transaction():
            for task in self.db.execute(
                "SELECT * FROM tasks WHERE room=? AND status='running'", (room,)
            ).fetchall():
                if task["origin"] == "bot:" + aid:
                    self.db.execute(
                        "UPDATE assignments SET status='revoked',lease_hash='',lease_until=0 WHERE task=? AND status IN ('queued','working')",
                        (task["id"],),
                    )
                    self.event(task["id"], "", "system", "origin_revoked", "")
                else:
                    self.db.execute(
                        "UPDATE assignments SET status='revoked',lease_hash='',lease_until=0 WHERE task=? AND worker=? AND status IN ('queued','working')",
                        (task["id"], aid),
                    )
                    if self.db.execute("SELECT changes()").fetchone()[0]:
                        self.event(task["id"], "", "system", "worker_revoked", aid)
                self.settle(task["id"])

    def demo_tick(self):
        # Explicit deterministic demo members only; never execute tools or external adapters.
        for room in self.store.list_rooms():
            for agent in self.db.execute(
                "SELECT a.id FROM agents a LEFT JOIN bots b ON b.id=a.id WHERE a.room=? AND a.kind='demo' AND COALESCE(b.disabled,0)=0 AND COALESCE(b.deleted,0)=0",
                (room["id"],),
            ).fetchall():
                actor = "bot:" + agent["id"]
                try:
                    items = self.inbox(room["id"], actor)
                except Problem as exc:
                    if exc.status not in (403, 404):
                        raise
                    continue
                for item in items:
                    if item["status"] != "queued":
                        continue
                    data = dict(
                        task_id=item["task_id"],
                        assignment_id=item["id"],
                        expected_attempt=item["attempt"],
                        request_id="demo-claim-" + item["id"] + "-" + str(item["attempt"]),
                    )
                    try:
                        claim = self.operate(room["id"], actor, "claim", data)
                        self.operate(
                            room["id"],
                            actor,
                            "update",
                            dict(
                                task_id=item["task_id"],
                                assignment_id=item["id"],
                                lease=claim["lease"],
                                attempt=claim["attempt"],
                                kind="completed",
                                body="[DEMO] " + item["instruction"][:300],
                                request_id="demo-result-"
                                + item["id"]
                                + "-"
                                + str(claim["attempt"]),
                            ),
                        )
                    except Problem:
                        pass
