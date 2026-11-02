import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest

from roundtable import Store
from server import make_server


class CLIIDs(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("Synthetic CLI")
        self.origin = self.store.add_agent(self.room["id"], "cli-origin")
        self.worker = self.store.add_agent(self.room["id"], "cli-worker")
        self.store.grant(self.room["id"], self.origin["id"], 20)
        self.task = self.store.handoffs.create(
            self.room["id"],
            "bot:cli-origin",
            {
                "title": "Synthetic",
                "request_id": "synthetic-create",
                "context": "Test",
                "assignments": [{"worker": "cli-worker", "instruction": "Read only"}],
                "budget": 1,
                "timeout_seconds": 600,
            },
        )
        self.server = make_server(self.store, "a" * 40, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.env = dict(
            os.environ,
            ROUNDTABLE_URL=f"http://127.0.0.1:{self.server.server_port}",
            ROUNDTABLE_ROOM=self.room["id"],
            ROUNDTABLE_AGENT="cli-origin",
            ROUNDTABLE_TOKEN=self.origin["token"],
        )
        self.cmd = [sys.executable, str(Path(__file__).resolve().parents[1] / "local_client.py")]

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.store.db.close()

    def test_positional_task_and_context_with_open_stdin(self):
        for args in (
            ["task", self.task["task_id"]],
            ["context", self.task["task_id"], "--body", "synthetic additional context"],
        ):
            with subprocess.Popen(
                self.cmd + args,
                env=self.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as child:
                self.assertEqual(child.wait(timeout=5), 0)
                self.assertNotIn(self.origin["token"].encode(), child.stdout.read())

    def test_stdin_compatibility_conflicts_and_bounded_wait(self):
        payload = json.dumps({"task_id": self.task["task_id"]})
        result = subprocess.run(
            self.cmd + ["task"],
            env=self.env,
            input=payload,
            text=True,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0)
        for args in (
            ["task", self.task["task_id"]],
            ["roundtrip", self.task["task_id"]],
            ["wait", self.task["task_id"], "--body", "wrong"],
        ):
            result = subprocess.run(
                self.cmd + args,
                env=self.env,
                input=payload,
                text=True,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 1)
        with subprocess.Popen(
            self.cmd + ["task"],
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as child:
            self.assertEqual(child.wait(timeout=5), 1)
