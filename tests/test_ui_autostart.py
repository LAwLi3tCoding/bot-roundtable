"""`ui --autostart`: the clickable launcher starts a stopped instance, then opens the page."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import local_runtime as runtime  # noqa: E402

OPENED = {"ok": True, "opened": True, "one_time_login": True, "expires_in": 60}


class AutostartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = runtime.private_dir(Path(self.temp.name).resolve() / "instance")
        self.config = {"server_port": 12345, "caffeinate": True}

    def tearDown(self):
        self.temp.cleanup()

    def test_ready_server_opens_without_starting(self):
        with (
            patch.object(runtime, "owned", return_value=123),
            patch.object(runtime, "ready", return_value=True),
            patch.object(runtime, "bring_up") as bring_up,
            patch.object(runtime, "open_ui", return_value=dict(OPENED)) as open_ui,
        ):
            result = runtime.autostart_ui(self.state, self.config)
        bring_up.assert_not_called()
        open_ui.assert_called_once_with(self.state, self.config)
        self.assertEqual(result["autostarted"], [])

    def test_stopped_server_starts_like_up_then_opens(self):
        (self.state / "runtime-key.env").write_text("")
        calls = []
        with (
            patch.object(runtime, "owned", return_value=None),
            patch.object(runtime, "ready", return_value=False),
            patch.object(
                runtime,
                "bring_up",
                side_effect=lambda *a, **k: calls.append(k) or {"started": ["server", "mcp"]},
            ),
            patch.object(runtime, "open_ui", return_value=dict(OPENED)) as open_ui,
        ):
            result = runtime.autostart_ui(self.state, self.config)
        self.assertEqual(calls, [{"without_tunnel": False, "no_caffeinate": False}])
        open_ui.assert_called_once()
        self.assertEqual(result["autostarted"], ["server", "mcp"])

    def test_without_runtime_key_skips_tunnel_and_keeps_caffeinate_choice(self):
        calls = []
        with (
            patch.object(runtime, "owned", return_value=None),
            patch.object(runtime, "ready", return_value=False),
            patch.object(
                runtime, "bring_up", side_effect=lambda *a, **k: calls.append(k) or {"started": []}
            ),
            patch.object(runtime, "open_ui", return_value=dict(OPENED)),
        ):
            runtime.autostart_ui(self.state, dict(self.config, caffeinate=False))
        self.assertEqual(calls, [{"without_tunnel": True, "no_caffeinate": True}])

    def test_concurrent_clicks_start_once(self):
        up = threading.Event()
        starts = []

        def bring_up(*args, **kwargs):
            starts.append(1)
            time.sleep(0.3)
            up.set()
            return {"started": ["server"]}

        results = []
        with (
            patch.object(runtime, "owned", side_effect=lambda *a: 123 if up.is_set() else None),
            patch.object(runtime, "ready", side_effect=lambda *a: up.is_set()),
            patch.object(runtime, "bring_up", side_effect=bring_up),
            patch.object(runtime, "open_ui", side_effect=lambda *a: dict(OPENED)),
        ):
            threads = [
                threading.Thread(
                    target=lambda: results.append(runtime.autostart_ui(self.state, self.config))
                )
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(sorted(len(r["autostarted"]) for r in results), [0, 1])

    def test_lock_wait_times_out_with_reason(self):
        with (
            patch.object(runtime, "AUTOSTART_LOCK_WAIT", 0.3),
            runtime.locked(self.state),
        ):
            with self.assertRaisesRegex(runtime.Failure, "instance_busy_try_again"):
                runtime.autostart_ui(self.state, self.config)

    def test_plain_lock_still_fails_fast(self):
        with runtime.locked(self.state):
            with self.assertRaises(OSError):
                with runtime.locked(self.state):
                    pass

    def run_main(self, autostart_effect):
        (self.state / "instance.json").write_text("{}")
        argv = ["local_runtime.py", "ui", "--state-dir", str(self.state), "--autostart"]
        out = io.StringIO()
        with (
            patch.object(sys, "argv", argv),
            patch.object(runtime, "load", return_value=self.config),
            patch.object(runtime, "autostart_ui", side_effect=autostart_effect),
            patch.object(runtime.sys, "platform", "darwin"),
            patch.object(runtime.shutil, "which", return_value="/usr/bin/osascript"),
            patch.object(runtime.subprocess, "Popen") as popen,
            contextlib.redirect_stdout(out),
        ):
            code = runtime.main()
        return code, json.loads(out.getvalue()), popen

    def test_start_failure_alerts_with_reason_and_log_path(self):
        code, result, popen = self.run_main(runtime.Failure("component_health_timeout"))
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "component_health_timeout")
        argv = popen.call_args.args[0]
        self.assertEqual(argv[0], "osascript")
        self.assertIn("component_health_timeout", argv[-1])
        self.assertIn(str(self.state / "logs"), argv[-1])

    def test_success_does_not_alert(self):
        code, result, popen = self.run_main(lambda *a: dict(OPENED, autostarted=["server"]))
        self.assertEqual(code, 0)
        self.assertTrue(result["opened"])
        popen.assert_not_called()

    def test_unexpected_error_alert_hides_details(self):
        code, result, popen = self.run_main(RuntimeError("synthetic-secret-detail"))
        self.assertEqual(result["reason"], "local_operation_failed")
        self.assertNotIn("synthetic-secret-detail", json.dumps(popen.call_args.args[0]))

    def test_notify_skipped_off_macos(self):
        with (
            patch.object(runtime.sys, "platform", "linux"),
            patch.object(runtime.subprocess, "Popen") as popen,
        ):
            self.assertFalse(runtime.notify_failure("x"))
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
