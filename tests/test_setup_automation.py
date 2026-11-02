"""Isolated synthetic instance contracts; never reads a developer's runtime directory."""

import argparse
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_runtime", ROOT / "scripts/local_runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = runtime.private_dir(Path(self.temp.name).resolve() / "instance & space")
        self.args = argparse.Namespace(
            origin="test-origin",
            worker="test-worker",
            allowance=20,
            server_port=port(),
            mcp_port=port(),
        )

    def tearDown(self):
        if (self.state / "instance.json").exists():
            config = runtime.load(self.state)
            for component in ("tunnel", "mcp", "server"):
                runtime.stop_component(self.state, config, component)
        self.temp.cleanup()

    def setup_instance(self):
        runtime.setup(self.state, self.args)
        return runtime.load(self.state)

    def test_setup_idempotent_permissions_and_scopes(self):
        config = self.setup_instance()
        before = {p.name: p.read_bytes() for p in self.state.iterdir() if p.suffix == ".env"}
        self.assertTrue(runtime.setup(self.state, self.args)["already_configured"])
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.state.iterdir() if p.suffix == ".env"}
        )
        for name in before:
            self.assertEqual((self.state / name).stat().st_mode & 0o777, 0o600)
        room = runtime.env_read(self.state / "room.env")
        self.assertEqual(room["ROUNDTABLE_ROOM"], config["room"])
        self.assertGreaterEqual(len(room["ROUNDTABLE_ROOM_TOKEN"]), 32)
        origin = runtime.env_read(self.state / "test-origin.env")
        worker = runtime.env_read(self.state / "test-worker.env")
        self.assertNotEqual(origin["ROUNDTABLE_TOKEN"], worker["ROUNDTABLE_TOKEN"])
        self.assertEqual(config["event_hosts"], [])
        with runtime.sqlite3.connect(self.state / "roundtable.db") as db:
            self.assertEqual(
                db.execute(
                    "SELECT allowance FROM agents WHERE room=? AND id=?",
                    (config["room"], config["origin"]),
                ).fetchone()[0],
                20,
            )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0], 1)

    def test_incomplete_never_reports_success_or_recreates(self):
        original = runtime.save

        def fail(path, text, replace=False):
            if Path(path).name == "tunnel.yaml":
                raise OSError("synthetic disk failure")
            return original(path, text, replace)

        with patch.object(runtime, "save", side_effect=fail), self.assertRaises(OSError):
            runtime.setup(self.state, self.args)
        self.assertFalse((self.state / "instance.json").exists())
        with self.assertRaisesRegex(runtime.Failure, "incomplete_or_foreign"):
            runtime.setup(self.state, self.args)

    def test_symlink_and_permissions_rejected(self):
        target = self.state / "target"
        runtime.save(target, "synthetic-secret")
        link = self.state / "link"
        link.symlink_to(target)
        with self.assertRaises(runtime.CredentialError):
            runtime.save(link, "replacement", True)
        target.chmod(0o644)
        with self.assertRaises(runtime.CredentialError):
            runtime.private_read(target)
        with self.assertRaises(runtime.CredentialError):
            runtime.private_dir(link)

    def test_hidden_key_and_routine_no_echo_or_overwrite(self):
        config = self.setup_instance()
        secret = "sk-" + "synthetic" * 8
        output = io.StringIO()
        with (
            patch.object(runtime, "hidden", return_value=secret),
            contextlib.redirect_stdout(output),
        ):
            runtime.configure_secret(self.state, config, "runtime-key", False)
        self.assertNotIn(secret, output.getvalue())
        with self.assertRaises(runtime.Failure):
            runtime.configure_secret(self.state, config, "runtime-key", False)
        with (
            patch.object(runtime, "hidden", return_value="wrong"),
            self.assertRaises(runtime.Failure),
        ):
            runtime.configure_secret(self.state, config, "runtime-key", True)
        with patch.object(
            runtime, "hidden", side_effect=["https://routine.example.com/private", "synthetic-key"]
        ):
            runtime.configure_secret(self.state, config, "routine", False)
        self.assertTrue(runtime.read_json(self.state / "routine.json")["explicit_opt_in"])
        self.assertEqual((self.state / "routine.json").stat().st_mode & 0o777, 0o600)

    def test_environment_and_profile_contract(self):
        config = self.setup_instance()
        config["proxy"] = "http://127.0.0.1:12345"
        runtime.env_save(
            self.state / "runtime-key.env", {"CONTROL_PLANE_API_KEY": "sk-synthetic-not-live-0000"}
        )
        with patch.dict(
            os.environ,
            {"HTTPS_PROXY": "http://untrusted.invalid", "ROUNDTABLE_TERMINAL_NOTIFICATIONS": "1"},
        ):
            env = runtime.child_env(self.state, config, "mcp")
        self.assertFalse(set(runtime.AMBIENT) & set(env))
        self.assertNotIn("ROUNDTABLE_TERMINAL_NOTIFICATIONS", env)
        self.assertTrue(env["ROUNDTABLE_TUNNEL_AUTH_HEADER"].startswith("Bearer "))
        cmd = runtime.command(self.state, config, "tunnel")
        self.assertIn("--profile-file", cmd)
        self.assertIn("--control-plane.http-proxy", cmd)
        self.assertNotIn("stdout", cmd)
        self.assertIn("--health.listen-addr", cmd)
        self.assertIn("server_urls:", (self.state / "tunnel.yaml").read_text())

    def test_plist_paths_are_escaped_and_not_loaded(self):
        self.setup_instance()
        output = self.state / "plist & <quoted>"
        self.assertFalse(runtime.render(self.state, output)["loaded"])
        for path in output.glob("*.plist"):
            value = plistlib.loads(path.read_bytes())
            self.assertIn(str(self.state), value["ProgramArguments"])
            self.assertFalse(value["RunAtLoad"])
            self.assertFalse(value["KeepAlive"])
            self.assertNotIn("TOKEN", path.read_text())

    def test_foreign_pid_and_occupied_port_never_taken_over(self):
        config = self.setup_instance()
        runtime.write_json(
            self.state / "server.pid.json",
            {
                "pid": os.getpid(),
                "stamp": runtime.process_stamp(os.getpid()),
                "identity": config["identity"],
                "component": "server",
            },
        )
        with self.assertRaisesRegex(runtime.Failure, "ownership"):
            runtime.stop_component(self.state, config, "server")
        (self.state / "server.pid.json").unlink()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", config["server_port"]))
            listener.listen()
            with self.assertRaises(OSError):
                runtime.start(self.state, config, "server")
        self.assertFalse((self.state / "server.pid.json").exists())

    def test_real_server_mcp_up_down_and_stale_pid(self):
        config = self.setup_instance()
        self.assertTrue(runtime.start(self.state, config, "server"))
        self.assertFalse(runtime.start(self.state, config, "server"))
        self.assertTrue(runtime.start(self.state, config, "mcp"))
        result = runtime.diagnostics(self.state, config)
        self.assertTrue(result["components"]["mcp"]["ready"])
        self.assertEqual(result["valid_subscriptions"], 0)
        self.assertEqual(result["origin_allowance"], 20)
        runtime.stop_component(self.state, config, "mcp")
        self.assertTrue(runtime.owned(self.state, config, "server"))
        runtime.stop_component(self.state, config, "server")
        runtime.write_json(
            self.state / "server.pid.json",
            {
                "pid": 99999999,
                "stamp": "stale",
                "identity": config["identity"],
                "component": "server",
            },
        )
        runtime.write_json(
            self.state / "server.stop.json",
            {"cleaned": True, "identity": config["identity"]},
            replace=True,
        )
        self.assertTrue(runtime.start(self.state, config, "server"))

    def test_pid_publication_failure_reaps_supervisor(self):
        config = self.setup_instance()
        original = runtime.write_json
        children = []
        popen = subprocess.Popen

        def capture(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child

        def fail(path, value, replace=False):
            if Path(path).name == "server.pid.json":
                raise OSError("synthetic write failure")
            return original(path, value, replace)

        with (
            patch.object(runtime, "write_json", side_effect=fail),
            patch.object(runtime.subprocess, "Popen", side_effect=capture),
            self.assertRaises(OSError),
        ):
            runtime.start(self.state, config, "server")
        self.assertTrue(all(c.poll() is not None for c in children))

    def test_start_failure_logs_are_fixed_categories(self):
        self.assertEqual(
            runtime.safe_log("ModuleNotFoundError: secret-value"),
            "component_error_dependency_missing\n",
        )
        self.assertEqual(
            runtime.safe_log("PermissionError: private-path"), "component_error_permission_denied\n"
        )
        self.assertEqual(
            runtime.safe_log("OSError: [Errno 98] private-value"),
            "component_error_address_in_use\n",
        )
        self.assertEqual(runtime.safe_log("ValueError: secret-value"), "")

    def test_safe_logs_discard_secrets_even_split_chunks(self):
        for value in (
            "Bearer synthetic-secret",
            "sk-abc",
            "https://example.com/secret",
            "token=abc",
            "a" * 20000,
        ):
            self.assertEqual(runtime.safe_log(value), "")
        self.assertEqual(
            runtime.safe_log("event_subscription_created secret=abc"),
            "event_subscription_created\n",
        )
        self.assertEqual(
            runtime.safe_log("callback_host_not_approved host=callback.example.com\n"),
            "callback_host_not_approved host=callback.example.com\n",
        )

    def test_supervisor_cleans_descendant_after_child_exits(self):
        config = self.setup_instance()
        marker = self.state / "descendant.pid"
        code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); open(sys.argv[1],'w').write(str(p.pid))"
        with patch.object(
            runtime, "command", return_value=[sys.executable, "-c", code, str(marker)]
        ):
            runtime.supervise(self.state, config, "server", config["identity"])
        pid = int(marker.read_text())
        deadline = time.monotonic() + 3
        while runtime.process_stamp(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(runtime.process_stamp(pid))

    def test_missing_stop_outcome_is_uncertain_not_stale_success(self):
        config = self.setup_instance()
        runtime.write_json(
            self.state / "server.pid.json",
            {
                "pid": 99999999,
                "stamp": "gone",
                "identity": config["identity"],
                "component": "server",
            },
        )
        with self.assertRaisesRegex(runtime.Failure, "cleanup_unconfirmed"):
            runtime.stop_component(self.state, config, "server")
        with self.assertRaisesRegex(runtime.Failure, "cleanup_unconfirmed"):
            runtime.start(self.state, config, "server")
        self.assertTrue((self.state / "server.pid.json").exists())
        (self.state / "server.pid.json").unlink()  # Synthetic record, never a real process.

    def test_wait_does_not_hold_lifecycle_lock(self):
        config = self.setup_instance()

        def waiting(*args):
            with runtime.locked(self.state):
                return {"status": "synthetic"}

        argv = [
            "local_runtime.py",
            "client",
            "--state-dir",
            str(self.state),
            "--operation",
            "wait",
            "--task-id",
            "a" * 24,
        ]
        with (
            patch.object(sys, "argv", argv),
            patch("local_client.LocalClient.wait", side_effect=waiting),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(runtime.main(), 0)
        self.assertEqual(runtime.load(self.state)["identity"], config["identity"])

    def test_owner_doctor_counts_only_its_worker(self):
        config = self.setup_instance()
        member = runtime.env_read(self.state / (config["worker"] + ".env"))
        runtime.save(self.state / "events.db", "")
        with runtime.sqlite3.connect(self.state / "events.db") as db:
            db.execute("CREATE TABLE subscriptions(principal TEXT, expires REAL)")
            principal = runtime.hashlib.sha256(member["ROUNDTABLE_TOKEN"].encode()).hexdigest()
            db.executemany(
                "INSERT INTO subscriptions VALUES (?,?)",
                [
                    (principal, time.time() + 100),
                    ("other-principal", time.time() + 200),
                    (principal, 1),
                ],
            )
        result = runtime.diagnostics(self.state, config)
        self.assertEqual(result["valid_subscriptions"], 1)
        self.assertNotIn("other-principal", str(result))
        self.assertNotIn(member["ROUNDTABLE_TOKEN"], str(result))

    def test_concurrent_setup_lock_and_nonprivate_existing_log(self):
        with runtime.locked(self.state), self.assertRaises(BlockingIOError):
            runtime.setup(self.state, self.args)
        config = self.setup_instance()
        runtime.private_dir(self.state / "logs")
        log = self.state / "logs/server.log"
        log.write_text("existing")
        log.chmod(0o644)
        with self.assertRaises(runtime.CredentialError):
            runtime.supervise(self.state, config, "server", config["identity"])

    def test_fake_tunnel_real_process_fifo_health_and_stop(self):
        config = self.setup_instance()
        fakebin = self.state / "bin"
        fakebin.mkdir(mode=0o700)
        fake = fakebin / "tunnel-client"
        fake.write_text(
            "#!"
            + sys.executable
            + "\n"
            + """import sys,os
from http.server import HTTPServer,BaseHTTPRequestHandler
from pathlib import Path
args=sys.argv
def arg(name): return args[args.index(name)+1]
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
    def log_message(self,*a): pass
s=HTTPServer(('127.0.0.1',0),H)
Path(arg('--health.url-file')).write_text('http://127.0.0.1:'+str(s.server_port))
Path(arg('--pid.file')).write_text(str(os.getpid()))
with open(arg('--log.file'),'w') as f:
    f.write('Bearer synthetic-not-for-logs\\nsk-synthetic-not-for-logs\\n'); f.flush()
s.serve_forever()
"""
        )
        fake.chmod(0o700)
        runtime.env_save(
            self.state / "runtime-key.env", {"CONTROL_PLANE_API_KEY": "sk-synthetic-not-live-0000"}
        )
        with patch.dict(os.environ, {"PATH": str(fakebin) + os.pathsep + os.environ["PATH"]}):
            self.assertTrue(runtime.start(self.state, config, "tunnel"))
        self.assertTrue(runtime.ready(self.state, config, "tunnel"))
        runtime.stop_component(self.state, config, "tunnel")
        self.assertFalse((self.state / "tunnel-log.pipe").exists())
        text = (self.state / "logs/tunnel.log").read_text()
        self.assertNotIn("synthetic-not-for-logs", text)
        self.assertEqual((self.state / "logs/tunnel.log").stat().st_mode & 0o777, 0o600)

    def test_started_marker_without_pid_blocks_restart_and_false_stop(self):
        config = self.setup_instance()
        marker = self.state / "server.started.json"
        runtime.write_json(marker, {"identity": config["identity"], "supervisor_pid": 99999999})
        with self.assertRaisesRegex(runtime.Failure, "cleanup_unconfirmed"):
            runtime.start(self.state, config, "server")
        with self.assertRaisesRegex(runtime.Failure, "cleanup_unconfirmed"):
            runtime.stop_component(self.state, config, "server")
        marker.unlink()  # Only a synthetic failure record; no process was started.

    def test_ambient_proxy_diagnosable_but_start_requires_explicit_choice(self):
        config = self.setup_instance()
        output = io.StringIO()
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://synthetic.invalid"}):
            self.assertTrue(runtime.diagnostics(self.state, config)["ambient_proxy_present"])
            with (
                patch.object(
                    sys,
                    "argv",
                    ["local_runtime.py", "up", "--without-tunnel", "--state-dir", str(self.state)],
                ),
                patch.object(runtime, "start") as start,
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(runtime.main(), 1)
                start.assert_not_called()
        self.assertIn("explicit_outbound_proxy_required", output.getvalue())
        self.assertNotIn("synthetic.invalid", output.getvalue())
