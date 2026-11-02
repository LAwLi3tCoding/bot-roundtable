"""Explicit Grok webhook notifications (kinds task.finished and mention) with a durable at-most-one-attempt ledger.

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

from state_paths import state_dir
from grok_adapter import GrokWebhook
from local_client import LocalClient
from outbound import OutboundConfigurationError, OutboundNotSentError

TERMINAL = {"completed", "failed", "timeout", "cancelled"}


_DELIVERY_SLOTS = threading.BoundedSemaphore(4)


def bounded_dispatch(adapter, tid, status, timeout=20, stop=None, transport=None):
    """Bound total wait, including DNS, without accumulating hung threads."""
    if stop is not None and stop.is_set():
        raise TimeoutError("terminal_delivery_cancelled")
    if not _DELIVERY_SLOTS.acquire(blocking=False):
        raise TimeoutError("terminal_delivery_capacity_exhausted")
    done, cancelled = threading.Event(), threading.Event()
    state = {"deadline": time.monotonic() + timeout}
    accepted: list = []

    def run():
        try:
            if isinstance(adapter, GrokWebhook):
                adapter.dispatch_terminal(
                    tid, status, cancelled=cancelled, state=state, transport=transport
                )
            else:
                adapter.dispatch_terminal(tid, status)
            accepted.append(True)
        except (OutboundConfigurationError, OutboundNotSentError) as exc:
            accepted.append(exc)
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
    if accepted and isinstance(accepted[0], Exception):
        raise accepted[0]
    if not accepted:
        raise TimeoutError("terminal_delivery_uncertain")


def private_ledger(path):
    """Create private storage without changing process-global umask or existing modes."""
    if str(path) == ":memory:":
        return
    target = Path(path)
    missing = []
    parent = target.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return
    else:
        os.close(fd)


class MentionAdapter(GrokWebhook):
    """Reuse the same bounded transport and durable reservation path for wake hints."""

    def __init__(self, adapter):
        self.adapter = adapter

    def preflight(self):
        return self.adapter.preflight()

    def dispatch_terminal(self, task_id, status, **kwargs):
        return self.adapter.notify("message", str(int(task_id, 16)), **kwargs)


class TerminalReceipts:
    def __init__(self, path, delivery_timeout=20, stop=None):
        self.stop = stop
        self.delivery_timeout = delivery_timeout
        private_ledger(path)
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

    def send_mention(self, scope, message_id, adapter):
        if type(message_id) is not int or not 0 < message_id < 2**63:
            raise ValueError("Invalid mention message ID")
        return self.send(
            "mention:" + scope,
            {"id": format(message_id, "024x"), "status": "completed"},
            MentionAdapter(adapter),
        )

    def send(self, scope, task, adapter):
        """Task must be freshly obtained through an authorized scoped query."""
        tid, status = task.get("id"), task.get("status")
        if not isinstance(tid, str) or not re.fullmatch(r"[a-f0-9]{24}", tid):
            raise ValueError("Invalid task ID")
        if status not in TERMINAL:
            return {"attempted": False, "reason": "task_not_terminal"}
        if self.db.execute(
            "SELECT 1 FROM terminal_delivery WHERE scope=? AND task_id=?", (scope, tid)
        ).fetchone():
            return {"attempted": False, "reason": "already_reserved"}
        transport = None
        if isinstance(adapter, GrokWebhook):
            try:
                transport = adapter.preflight()
            except OutboundConfigurationError as exc:
                return {
                    "attempted": False,
                    "outcome": "definitely_not_sent",
                    "reason": exc.code
                    if isinstance(exc, OutboundConfigurationError)
                    else "outbound_definitely_not_sent",
                }
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
            bounded_dispatch(
                adapter, tid, status, self.delivery_timeout, self.stop, transport=transport
            )
        except (OutboundConfigurationError, OutboundNotSentError) as exc:
            with self.db:
                self.db.execute(
                    "UPDATE terminal_delivery SET outcome='definitely_not_sent' WHERE scope=? AND task_id=?",
                    (scope, tid),
                )
            return {
                "attempted": True,
                "outcome": "definitely_not_sent",
                "reason": exc.code
                if isinstance(exc, OutboundConfigurationError)
                else "outbound_definitely_not_sent",
            }
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
        self.health = {"state": "starting", "reason": "", "retry_seconds": 0}
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(5):
            self.stop_event.set()
            raise RuntimeError("terminal_worker_start_failed")

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=1)

    def status(self):
        return dict(self.health)

    def _run(self):
        delay = 0.1
        while not self.stop_event.is_set():
            try:
                self._session()
                break
            except Exception as exc:
                self.failed = True
                reason = (
                    exc.code
                    if isinstance(exc, OutboundConfigurationError)
                    else "terminal_worker_fault"
                )
                self.health = {"state": "backoff", "reason": reason, "retry_seconds": delay}
                self.ready.set()
                logging.warning("terminal_worker_backoff")
                if self.stop_event.wait(delay):
                    break
                delay = min(delay * 2, 30)
        self.health = {"state": "stopped", "reason": "", "retry_seconds": 0}

    def _session(self):
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
            mention_key = "mention:" + key
            mention_enabled = (
                source.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('mail_messages','mail_deliveries')"
                ).fetchone()[0]
                == 2
            )
            mention_current = (
                source.execute("SELECT COALESCE(MAX(id),0) FROM mail_messages").fetchone()[0]
                if mention_enabled
                else 0
            )
            with ledger.db:
                ledger.db.execute(
                    "INSERT OR IGNORE INTO terminal_cursor VALUES(?,?)",
                    (mention_key, mention_current),
                )
            mention_cursor = ledger.db.execute(
                "SELECT position FROM terminal_cursor WHERE scope=?", (mention_key,)
            ).fetchone()[0]
            self.failed = False
            self.health = {"state": "running", "reason": "", "retry_seconds": 0}
            self.ready.set()
            while not self.stop_event.is_set():
                mentions = (
                    source.execute(
                        "SELECT n.message FROM mail_deliveries n JOIN mail_messages m ON m.id=n.message JOIN mail_topics t ON t.id=m.topic JOIN agents a ON a.room=t.room AND 'bot:'||a.id=n.actor AND a.token=n.epoch JOIN mail_members mm ON mm.topic=t.id AND mm.actor=n.actor AND mm.epoch=n.epoch WHERE t.room=? AND a.id=? AND n.wake=1 AND t.stopped=0 AND n.message>? ORDER BY n.message LIMIT 100",
                        (self.room, self.origin, mention_cursor),
                    ).fetchall()
                    if mention_enabled
                    else []
                )
                for mention in mentions:
                    if self.stop_event.is_set():
                        break
                    # Recheck each item after any preceding network wait; an in-flight
                    # request cannot be recalled, but queued revoked work is skipped.
                    current_mention = source.execute(
                        "SELECT 1 FROM mail_deliveries n JOIN mail_messages m ON m.id=n.message JOIN mail_topics t ON t.id=m.topic JOIN agents a ON a.room=t.room AND 'bot:'||a.id=n.actor AND a.token=n.epoch JOIN mail_members mm ON mm.topic=t.id AND mm.actor=n.actor AND mm.epoch=n.epoch WHERE t.room=? AND a.id=? AND n.wake=1 AND t.stopped=0 AND n.message=?",
                        (self.room, self.origin, mention["message"]),
                    ).fetchone()
                    result = (
                        ledger.send_mention(key, mention["message"], self.adapter)
                        if current_mention
                        else {"attempted": False}
                    )
                    if result.get("outcome") == "definitely_not_sent" and not result["attempted"]:
                        raise OutboundConfigurationError(result["reason"])
                    mention_cursor = mention["message"]
                    with ledger.db:
                        ledger.db.execute(
                            "UPDATE terminal_cursor SET position=? WHERE scope=?",
                            (mention_cursor, mention_key),
                        )
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
                        if (
                            result.get("outcome") == "definitely_not_sent"
                            and not result["attempted"]
                        ):
                            raise OutboundConfigurationError(result["reason"])
                        if result.get("outcome") == "uncertain":
                            logging.warning("terminal_delivery_uncertain")
                    cursor = row["event_id"]
                    with ledger.db:
                        ledger.db.execute(
                            "UPDATE terminal_cursor SET position=? WHERE scope=?", (cursor, key)
                        )
                if len(rows) < 100:
                    self.stop_event.wait(self.interval)
        finally:
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
    ledger = os.environ.get("ROUNDTABLE_TERMINAL_LEDGER", str(state_dir() / "terminal-receipts.db"))
    private_ledger(ledger)
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
        default=os.environ.get(
            "ROUNDTABLE_TERMINAL_LEDGER", str(state_dir() / "terminal-receipts.db")
        ),
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
        ledger = TerminalReceipts(args.ledger)
        scope = os.environ["ROUNDTABLE_ROOM"]
        result = ledger.send(scope, task, adapter)
        print(json.dumps(result))
        return 1 if result.get("outcome") in ("uncertain", "definitely_not_sent") else 0
    except Exception:
        print(json.dumps({"ok": False, "reason": "terminal_receipt_failed_or_uncertain"}))
        return 1
    finally:
        if ledger:
            ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
