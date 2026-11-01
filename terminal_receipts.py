"""Explicit terminal notifications with a durable at-most-one-attempt ledger.

Reserve before network I/O. A crash after reservation can lose a notification;
a crash after delivery can leave its outcome unknown. Neither is auto-retried.
This is not exactly-once delivery. Keep the ledger across restarts and backups.
"""

import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import threading
import logging
import socket

from grok_adapter import GrokWebhook
from local_client import LocalClient

TERMINAL = {"completed", "failed", "timeout", "cancelled"}


_DELIVERY_SLOTS = threading.BoundedSemaphore(4)


def bounded_dispatch(adapter, tid, status, timeout=20, stop=None):
    """Bound total wait, including DNS, without accumulating hung threads."""
    if stop is not None and stop.is_set():
        raise TimeoutError("terminal_delivery_cancelled")
    if not _DELIVERY_SLOTS.acquire(blocking=False):
        raise TimeoutError("terminal_delivery_capacity_exhausted")
    done, cancelled = threading.Event(), threading.Event()
    state = {"deadline": time.monotonic() + timeout}
    accepted = []

    def run():
        try:
            if isinstance(adapter, GrokWebhook):
                adapter.dispatch_terminal(tid, status, cancelled=cancelled, state=state)
            else:
                adapter.dispatch_terminal(tid, status)
            accepted.append(True)
        except Exception:
            pass
        finally:
            _DELIVERY_SLOTS.release()
            done.set()

    threading.Thread(target=run, daemon=True).start()
    while not done.wait(min(0.05, max(0, state["deadline"] - time.monotonic()))):
        if time.monotonic() >= state["deadline"] or (stop is not None and stop.is_set()):
            cancelled.set()
            connection = state.get("connection")
            sock = state.get("socket") or getattr(connection, "sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            raise TimeoutError("terminal_delivery_uncertain")
    if not accepted:
        raise TimeoutError("terminal_delivery_uncertain")


class TerminalReceipts:
    def __init__(self, path, delivery_timeout=20, stop=None):
        self.stop = stop
        self.delivery_timeout = delivery_timeout
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS terminal_delivery("
            "scope TEXT, task_id TEXT, status TEXT, outcome TEXT, attempted REAL, "
            "PRIMARY KEY(scope, task_id))"
        )
        self.db.commit()

    def close(self):
        self.db.close()

    def send(self, scope, task, adapter):
        """Task must be freshly obtained through an authorized scoped query."""
        tid, status = task.get("id"), task.get("status")
        if not isinstance(tid, str) or not re.fullmatch(r"[a-f0-9]{24}", tid):
            raise ValueError("Invalid task ID")
        if status not in TERMINAL:
            return {"attempted": False, "reason": "task_not_terminal"}
        # Atomic uniqueness serializes competing processes without holding a lock
        # during network I/O. Unknown is deliberately persisted before dispatch.
        with self.db:
            inserted = self.db.execute(
                "INSERT OR IGNORE INTO terminal_delivery VALUES(?,?,?,?,?)",
                (scope, tid, status, "uncertain", time.time()),
            ).rowcount
        if not inserted:
            return {"attempted": False, "reason": "already_reserved"}
        try:
            bounded_dispatch(adapter, tid, status, self.delivery_timeout, self.stop)
        except Exception:
            # Error details could contain the callback URL or credentials.
            return {"attempted": True, "outcome": "uncertain", "task_id": tid}
        with self.db:
            self.db.execute(
                "UPDATE terminal_delivery SET outcome='accepted' WHERE scope=? AND task_id=?",
                (scope, tid),
            )
        return {"attempted": True, "outcome": "accepted", "task_id": tid}


class TerminalWorker:
    """Default-disabled observer. Own DB connections; never holds Store locks over I/O."""

    def __init__(self, source, ledger, room, origin, adapter, interval=0.5):
        if not re.fullmatch(r"[a-f0-9]{24}", room) or not re.fullmatch(
            r"[a-z][a-z0-9-]{1,39}", origin
        ):
            raise ValueError("Explicit terminal notification room and origin required")
        self.source, self.ledger = str(source), str(ledger)
        self.room, self.origin, self.adapter = room, origin, adapter
        self.interval = interval
        self.stop_event, self.ready = threading.Event(), threading.Event()
        self.failed = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(5) or self.failed:
            self.stop_event.set()
            raise RuntimeError("terminal_worker_start_failed")

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=1)

    def _run(self):
        source = None
        ledger = None
        try:
            source = sqlite3.connect(Path(self.source).resolve().as_uri() + "?mode=ro", uri=True)
            source.row_factory = sqlite3.Row
            if not source.execute(
                "SELECT 1 FROM agents WHERE room=? AND id=?", (self.room, self.origin)
            ).fetchone():
                raise ValueError("Terminal origin is not a current room member")
            namespace = source.execute("SELECT value FROM event_namespace WHERE id=1").fetchone()[0]
            key = namespace + ":" + self.room + ":" + self.origin
            ledger = TerminalReceipts(self.ledger, stop=self.stop_event)
            ledger.db.execute(
                "CREATE TABLE IF NOT EXISTS terminal_cursor(scope TEXT PRIMARY KEY, position INTEGER)"
            )
            current = source.execute("SELECT COALESCE(MAX(id),0) FROM task_events").fetchone()[0]
            with ledger.db:
                ledger.db.execute(
                    "INSERT OR IGNORE INTO terminal_cursor VALUES(?,?)", (key, current)
                )
            cursor = ledger.db.execute(
                "SELECT position FROM terminal_cursor WHERE scope=?", (key,)
            ).fetchone()[0]
            self.ready.set()
            while not self.stop_event.is_set():
                rows = source.execute(
                    "SELECT e.id AS event_id,e.kind,t.id,t.status,t.room,t.origin,"
                    "t.origin_epoch=a.token AS epoch_valid FROM task_events e "
                    "LEFT JOIN tasks t ON t.id=e.task "
                    "LEFT JOIN agents a ON a.room=t.room AND a.id=? "
                    "WHERE e.id>? ORDER BY e.id LIMIT 100",
                    (self.origin, cursor),
                ).fetchall()
                # fetchall completes the read statement before any network operation.
                for row in rows:
                    if self.stop_event.is_set():
                        break
                    current_task = source.execute(
                        "SELECT t.id,t.status,t.room,t.origin,t.origin_epoch=a.token AS epoch_valid "
                        "FROM tasks t LEFT JOIN agents a ON a.room=t.room AND a.id=? WHERE t.id=?",
                        (self.origin, row["id"]),
                    ).fetchone()
                    if (
                        current_task is not None
                        and row["kind"]
                        in ("task_completed", "task_failed", "task_timeout", "cancelled")
                        and current_task["room"] == self.room
                        and current_task["origin"] == "bot:" + self.origin
                        and current_task["epoch_valid"]
                        and current_task["status"] in TERMINAL
                    ):
                        result = ledger.send(self.room, dict(current_task), self.adapter)
                        if result.get("outcome") == "uncertain":
                            logging.warning("terminal_delivery_uncertain")
                    cursor = row["event_id"]
                    with ledger.db:
                        ledger.db.execute(
                            "UPDATE terminal_cursor SET position=? WHERE scope=?", (cursor, key)
                        )
                if len(rows) < 100:
                    self.stop_event.wait(self.interval)
        except Exception:
            self.failed = True
            logging.error("terminal_worker_failed")
        finally:
            self.ready.set()
            if ledger:
                ledger.close()
            if source:
                source.close()


def configured_worker(source):
    """No config/secret lookup or thread when disabled; inherit explicitly enabled env."""
    if os.environ.get("ROUNDTABLE_TERMINAL_NOTIFICATIONS") != "1":
        return None
    adapter = GrokWebhook(
        os.environ["GROK_ROUTINE_URL"],
        os.environ["GROK_ROUTINE_KEY"],
        os.environ["GROK_ALLOWED_HOST"],
    )
    ledger = os.environ.get("ROUNDTABLE_TERMINAL_LEDGER", "data/terminal-receipts.db")
    Path(ledger).parent.mkdir(parents=True, exist_ok=True)
    return TerminalWorker(
        source,
        ledger,
        os.environ["ROUNDTABLE_TERMINAL_ROOM"],
        os.environ["ROUNDTABLE_TERMINAL_ORIGIN"],
        adapter,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--dispatch-terminal", action="store_true", required=True)
    parser.add_argument(
        "--ledger",
        default=os.environ.get("ROUNDTABLE_TERMINAL_LEDGER", "data/terminal-receipts.db"),
    )
    parser.add_argument("--wait", type=float, default=0, metavar="SECONDS")
    args = parser.parse_args()
    if not 0 <= args.wait <= 86400:
        parser.error("wait must be 0–86400 seconds")
    ledger = None
    try:
        # Inherit authorized environment references; never parse credential files.
        client = LocalClient(
            os.environ.get("ROUNDTABLE_URL", "http://127.0.0.1:8765"),
            os.environ["ROUNDTABLE_ROOM"],
            os.environ["ROUNDTABLE_AGENT"],
            os.environ["ROUNDTABLE_TOKEN"],
        )
        snapshot = (
            client.wait(args.task_id, args.wait)
            if args.wait
            else client.call("task", {"task_id": args.task_id})
        )
        task = snapshot["task"]
        if task["status"] not in TERMINAL:
            print(json.dumps({"attempted": False, "reason": "task_not_terminal"}))
            return 0
        adapter = GrokWebhook(
            os.environ["GROK_ROUTINE_URL"],
            os.environ["GROK_ROUTINE_KEY"],
            os.environ["GROK_ALLOWED_HOST"],
        )
        os.umask(0o077)
        Path(args.ledger).parent.mkdir(parents=True, exist_ok=True)
        ledger = TerminalReceipts(args.ledger)
        scope = os.environ["ROUNDTABLE_ROOM"]
        result = ledger.send(scope, task, adapter)
        print(json.dumps(result))
        return 1 if result.get("outcome") == "uncertain" else 0
    except Exception:
        print(json.dumps({"ok": False, "reason": "terminal_receipt_failed_or_uncertain"}))
        return 1
    finally:
        if ledger:
            ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
