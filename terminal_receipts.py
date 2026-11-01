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

from grok_adapter import GrokWebhook
from local_client import LocalClient

TERMINAL = {"completed", "failed", "timeout", "cancelled"}


class TerminalReceipts:
    def __init__(self, path):
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
            adapter.dispatch_terminal(tid, status)
        except Exception:
            # Error details could contain the callback URL or credentials.
            return {"attempted": True, "outcome": "uncertain", "task_id": tid}
        with self.db:
            self.db.execute(
                "UPDATE terminal_delivery SET outcome='accepted' WHERE scope=? AND task_id=?",
                (scope, tid),
            )
        return {"attempted": True, "outcome": "accepted", "task_id": tid}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--dispatch-terminal", action="store_true", required=True)
    parser.add_argument("--ledger", default="data/terminal-receipts.db")
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
        deadline = time.monotonic() + args.wait
        while True:
            task = client.call("task", {"task_id": args.task_id})["task"]
            if task["status"] in TERMINAL or time.monotonic() >= deadline:
                break
            time.sleep(min(1, max(0, deadline - time.monotonic())))
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
