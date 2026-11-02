"""Only fake caffeinate is executed; these tests never request OS sleep assertions."""

import contextlib
import io
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

import test_setup_automation as fixture

runtime = fixture.runtime


class SleepTests(unittest.TestCase):
    setUp = fixture.SetupTests.setUp
    setup_instance = fixture.SetupTests.setup_instance

    def tearDown(self):
        if (self.state / "instance.json").exists():
            config = runtime.load(self.state)
            for component in ("tunnel", "mcp", "caffeinate", "server"):
                runtime.stop_component(self.state, config, component)
        self.temp.cleanup()

    def fake_binary(self):
        folder = self.state / "fake-bin"
        folder.mkdir(mode=0o700)
        binary = folder / "caffeinate"
        binary.write_text(
            "#!"
            + sys.executable
            + "\n"
            + """import os,sys,time
assert sys.argv[1:4] == ['-i','-s','-w']
pid=int(sys.argv[4])
while True:
    try: os.kill(pid,0)
    except ProcessLookupError: break
    time.sleep(.05)
"""
        )
        binary.chmod(0o700)
        return folder

    def run_up(self, *flags):
        output = io.StringIO()
        argv = [
            "local_runtime.py",
            "up",
            "--component",
            "server",
            "--state-dir",
            str(self.state),
            *flags,
        ]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
            code = runtime.main()
        return code, json.loads(output.getvalue())

    @unittest.skipUnless(sys.platform == "darwin", "macOS fake-process lifecycle contract")
    def test_default_fake_assertion_status_and_no_caffeinate_flag(self):
        self.setup_instance()
        folder = self.fake_binary()
        env = {key: "" for key in runtime.AMBIENT}
        env["PATH"] = str(folder) + os.pathsep + os.environ["PATH"]
        with patch.dict(os.environ, env):
            code, result = self.run_up()
            self.assertEqual(code, 0)
            self.assertIn("caffeinate", result["started"])
            config = runtime.load(self.state)
            report = runtime.diagnostics(self.state, config)["sleep_prevention"]
            self.assertTrue(report["process_running"])
            self.assertTrue(report["server_bound"])
            self.assertTrue(report["system_sleep_requires_ac"])
            self.assertFalse(report["os_assertion_verified"])
            self.assertFalse(
                any("TOKEN" in k for k in runtime.child_env(self.state, config, "caffeinate"))
            )
            code, result = self.run_up("--no-caffeinate")
            self.assertEqual(code, 0)
            self.assertEqual(result["sleep_prevention"]["state"], "disabled")
            self.assertFalse(runtime.owned(self.state, config, "caffeinate"))
            self.assertTrue(runtime.owned(self.state, config, "server"))

    @unittest.skipUnless(sys.platform == "darwin", "macOS fake-process lifecycle contract")
    def test_server_exit_releases_fake_process_without_orphan(self):
        config = self.setup_instance()
        folder = self.fake_binary()
        with patch.dict(os.environ, {"PATH": str(folder) + os.pathsep + os.environ["PATH"]}):
            runtime.start(self.state, config, "server")
            runtime.start(self.state, config, "caffeinate")
            child = runtime.read_json(self.state / "caffeinate.child.json")["pid"]
            runtime.stop_component(self.state, config, "server")
            deadline = time.monotonic() + 5
            while runtime.process_stamp(child) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(runtime.process_stamp(child))
            runtime.stop_component(self.state, config, "caffeinate")

    def test_unsupported_or_missing_binary_skips_without_starting_assertions(self):
        self.setup_instance()
        env = {key: "" for key in runtime.AMBIENT}
        for platform, binary, reason in (
            ("linux", "/not-used", "non_macos"),
            ("darwin", None, "binary_unavailable"),
        ):
            with (
                patch.dict(os.environ, env),
                patch.object(runtime.sys, "platform", platform),
                patch.object(runtime.shutil, "which", return_value=binary),
                patch.object(runtime, "start", return_value=False) as start,
            ):
                code, result = self.run_up()
            self.assertEqual(code, 0)
            self.assertEqual(result["sleep_prevention"]["reason"], reason)
            self.assertEqual([call.args[2] for call in start.call_args_list], ["server"])

    def test_server_start_failure_never_spawns_caffeinate(self):
        self.setup_instance()
        env = {key: "" for key in runtime.AMBIENT}
        with (
            patch.dict(os.environ, env),
            patch.object(runtime.shutil, "which", return_value="/synthetic/caffeinate"),
            patch.object(
                runtime, "start", side_effect=runtime.Failure("synthetic_start_failure")
            ) as start,
        ):
            code, _ = self.run_up()
        self.assertEqual(code, 1)
        self.assertEqual([call.args[2] for call in start.call_args_list], ["server"])

    def test_foreign_caffeinate_pid_never_signalled(self):
        config = self.setup_instance()
        runtime.write_json(
            self.state / "caffeinate.pid.json",
            {
                "pid": os.getpid(),
                "stamp": runtime.process_stamp(os.getpid()),
                "identity": config["identity"],
                "component": "caffeinate",
            },
        )
        with (
            patch.object(runtime.os, "kill") as kill,
            self.assertRaisesRegex(runtime.Failure, "ownership"),
        ):
            runtime.stop_component(self.state, config, "caffeinate")
        kill.assert_not_called()
        (self.state / "caffeinate.pid.json").unlink()
