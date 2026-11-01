import contextlib
import importlib.util
import io
import json
import os
import plistlib
import secrets
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from roundtable import Store
from server import make_server

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("Synthetic script test")["id"]
        self.agent = self.store.add_agent(self.room, "script-worker")
        self.admin = secrets.token_urlsafe(32)
        self.server = make_server(self.store, self.admin, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.env = dict(
            os.environ,
            ROUNDTABLE_URL=f"http://127.0.0.1:{self.server.server_port}",
            ROUNDTABLE_ROOM=self.room,
            ROUNDTABLE_AGENT=self.agent["id"],
            ROUNDTABLE_TOKEN=self.agent["token"],
        )

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.store.db.close()

    def test_wrapper_stdin_open_and_closed(self):
        for stdin in (subprocess.PIPE, subprocess.DEVNULL):
            with subprocess.Popen(
                [sys.executable, str(ROOT / "scripts/check.py"), "probe"],
                env=self.env,
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as child:
                # Deliberately wait without communicate(): PIPE remains open, no EOF.
                self.assertEqual(child.wait(timeout=5), 0)
                stdout, stderr = child.stdout.read(), child.stderr.read()
                result = json.loads(stdout)
                self.assertEqual(result["agent"], self.agent["id"])
                self.assertIn("15s limit", stderr)
                self.assertNotIn(self.agent["token"], stdout + stderr)

    def test_wrapper_timeout_reaps_child_and_does_not_read_secret_file(self):
        module = load_script("check")
        original_run, original_popen = subprocess.run, subprocess.Popen
        children = []

        def capture(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            children.append(child)
            return child

        def stalled(*args, **kwargs):
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["timeout"], 15)
            kwargs["timeout"] = 0.05
            return original_run([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)

        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["check.py", "probe"]),
            patch.object(module.subprocess, "run", side_effect=stalled),
            patch.object(module.subprocess, "Popen", side_effect=capture),
            patch.object(Path, "read_text", side_effect=AssertionError("No secret file reads")),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(module.main(), 124)
        self.assertEqual(json.loads(output.getvalue())["reason"], "probe_total_timeout")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_admin_allowance_real_http_and_rejected_credential(self):
        command = [
            sys.executable,
            str(ROOT / "scripts/admin.py"),
            "allowance",
            self.room,
            self.agent["id"],
            "1",
        ]
        for token, status in ((self.agent["token"], 403), (self.admin, 200)):
            result = subprocess.run(
                command,
                env=dict(self.env, ROUNDTABLE_ADMIN_TOKEN=token),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(json.loads(result.stdout)["status"], status)
            self.assertEqual(result.returncode, 0 if status == 200 else 1)
            self.assertNotIn(token, result.stdout + result.stderr)
        row = self.store.db.execute(
            "SELECT allowance FROM agents WHERE room=? AND id=?", (self.room, self.agent["id"])
        ).fetchone()
        self.assertEqual(row["allowance"], 1)

    def test_launchd_templates_are_valid_and_inactive(self):
        paths = list((ROOT / "deploy/launchd").glob("*.plist.template"))
        self.assertEqual(len(paths), 3)
        for path in paths:
            data = plistlib.loads(path.read_bytes())
            self.assertFalse(data["RunAtLoad"])
            self.assertFalse(data["KeepAlive"])
            self.assertIn("${ROUNDTABLE_HOME}", data["ProgramArguments"][1])
