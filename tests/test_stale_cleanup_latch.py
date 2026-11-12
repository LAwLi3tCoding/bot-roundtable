"""Stale descendant-cleanup markers: recover when leftovers are gone, refuse when live."""

import argparse
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_runtime", ROOT / "scripts/local_runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
from runtime_lifecycle import require_stopped  # noqa: E402


class StaleCleanupLatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = runtime.private_dir(Path(self.temp.name).resolve() / "instance")
        self.args = argparse.Namespace(
            origin="test-origin",
            worker="test-worker",
            allowance=20,
            server_port=None,
            mcp_port=None,
        )

    def tearDown(self):
        if (self.state / "instance.json").exists():
            config = runtime.load(self.state)
            for component in ("tunnel", "mcp", "server"):
                try:
                    runtime.stop_component(self.state, config, component)
                except runtime.Failure:
                    pass
        self.temp.cleanup()

    def setup_instance(self):
        runtime.setup(self.state, self.args)
        return runtime.load(self.state)

    def write_stale_markers(
        self, config, component="server", child_pid=99999998, child_command=None
    ):
        runtime.write_json(
            self.state / (component + ".pid.json"),
            {
                "pid": 99999999,
                "stamp": "gone-supervisor",
                "identity": config["identity"],
                "component": component,
            },
        )
        runtime.write_json(
            self.state / (component + ".started.json"),
            {"identity": config["identity"], "supervisor_pid": 99999999},
        )
        runtime.write_json(
            self.state / (component + ".child.json"),
            {
                "pid": child_pid,
                "identity": config["identity"],
                "command": child_command or [sys.executable, "-c", "pass"],
            },
        )
        runtime.write_json(
            self.state / (component + ".stop.json"),
            {"cleaned": False, "identity": config["identity"]},
            replace=True,
        )

    def test_unconfirmed_markers_are_reaped_when_processes_are_gone(self):
        config = self.setup_instance()
        self.write_stale_markers(config)
        self.assertTrue(runtime.start(self.state, config, "server"))
        self.assertTrue(runtime.owned(self.state, config, "server"))
        self.assertFalse((self.state / "server.stop.json").exists())
        archive = self.state / "reaped-cleanup"
        self.assertTrue(archive.is_dir())
        self.assertEqual(archive.stat().st_mode & 0o777, 0o700)
        names = [path.name for path in archive.iterdir()]
        for suffix in (".pid.json", ".started.json", ".stop.json", ".child.json"):
            self.assertTrue(
                any(name.endswith("server" + suffix) for name in names),
                suffix,
            )
        runtime.stop_component(self.state, config, "server")

    def test_stop_and_require_stopped_reap_unconfirmed_markers_when_gone(self):
        config = self.setup_instance()
        self.write_stale_markers(config, component="mcp")
        runtime.stop_component(self.state, config, "mcp")
        self.assertFalse((self.state / "mcp.pid.json").exists())
        self.assertFalse((self.state / "mcp.stop.json").exists())
        self.write_stale_markers(config, component="server")
        require_stopped(self.state, config, runtime)
        self.assertFalse((self.state / "server.pid.json").exists())
        self.assertFalse((self.state / "server.started.json").exists())
        self.assertFalse((self.state / "server.child.json").exists())

    def test_unconfirmed_markers_still_block_when_child_is_live(self):
        config = self.setup_instance()
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        child = subprocess.Popen(
            command,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self.write_stale_markers(config, child_pid=child.pid, child_command=command)
            with self.assertRaisesRegex(
                runtime.Failure, "cleanup_unconfirmed leftover_processes_still_running"
            ):
                runtime.start(self.state, config, "server")
            with self.assertRaisesRegex(
                runtime.Failure, "cleanup_unconfirmed leftover_processes_still_running"
            ):
                runtime.stop_component(self.state, config, "server")
            with self.assertRaisesRegex(
                runtime.Failure, "cleanup_unconfirmed leftover_processes_still_running"
            ):
                require_stopped(self.state, config, runtime)
            try:
                runtime.start(self.state, config, "server")
            except runtime.Failure as exc:
                message = str(exc)
            else:
                self.fail("start should refuse while the child is live")
            self.assertIn("doctor", message)
            self.assertIn("--state-dir", message)
            self.assertIn(str(self.state), message)
            self.assertTrue((self.state / "server.stop.json").exists())
            self.assertFalse((self.state / "reaped-cleanup").exists())
        finally:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=3)

    def test_wait_error_after_group_exits_still_marks_cleaned(self):
        class Fake:
            pid = 99999999
            stdout = None

            def wait(self, timeout=None):
                raise RuntimeError("synthetic wait failure")

        self.assertTrue(runtime.stop_child_group(Fake(), None))
