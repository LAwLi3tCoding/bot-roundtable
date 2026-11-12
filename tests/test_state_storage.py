"""Platform paths and stopped-instance maintenance, entirely synthetic and temporary."""

import argparse
import contextlib
import io
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import admin_credentials as credentials
from private_logs import RotatingLog
from state_paths import state_dir, log_dir, path_warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import local_runtime as runtime  # noqa: E402
from runtime_lifecycle import require_stopped  # noqa: E402


class Paths(unittest.TestCase):
    def test_new_parent_chain_private_without_umask_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / "state-root" / "instance" / "admin-credentials"
            with patch.object(os, "umask", side_effect=AssertionError("global umask")):
                credentials.private_directory(target)
            for path in (target, target.parent, target.parent.parent):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            (root / "public").mkdir(mode=0o755)
            (root / "public").chmod(0o755)
            with self.assertRaises(credentials.CredentialError):
                credentials.private_directory(root / "public")

    def test_platform_defaults_and_name(self):
        home = Path("/synthetic-home")
        self.assertEqual(
            state_dir(name="alpha", environ={}, platform="darwin", home=home),
            home / "Library/Application Support/bot-roundtable/alpha",
        )
        self.assertEqual(
            log_dir(home / "state", name="alpha", platform="darwin", home=home),
            home / "Library/Logs/bot-roundtable/alpha",
        )
        self.assertEqual(
            state_dir(environ={}, platform="linux", home=home),
            home / ".local/state/bot-roundtable/default",
        )
        self.assertEqual(
            state_dir(environ={"LOCALAPPDATA": "/synthetic-local"}, platform="win32", home=home),
            Path("/synthetic-local/bot-roundtable/default"),
        )
        self.assertEqual(
            state_dir(environ={"XDG_STATE_HOME": "/synthetic-state"}, platform="linux"),
            Path("/synthetic-state/bot-roundtable/default"),
        )
        self.assertEqual(
            log_dir(home / "custom", custom_state=True, platform="darwin", home=home),
            home / "custom/logs",
        )

    def test_priority_invalid_names_and_relative_xdg(self):
        env = {
            "ROUNDTABLE_STATE_DIR": "/environment-state",
            "ROUNDTABLE_HOME": "/code-only",
            "ROUNDTABLE_INSTANCE_NAME": "beta",
        }
        self.assertEqual(state_dir("/explicit", environ=env), Path("/explicit"))
        self.assertEqual(state_dir(environ=env), Path("/environment-state"))
        for name in ("../escape", "a/b", "..", "name with space"):
            with self.assertRaisesRegex(ValueError, "invalid_instance_name"):
                state_dir(name=name, environ={})
        with self.assertRaises(ValueError):
            state_dir(environ={"XDG_STATE_HOME": "relative"}, platform="linux")
        with self.assertRaises(ValueError):
            state_dir(environ={}, platform="win32")

    def test_cwd_independent_subprocess_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("ROUNDTABLE_STATE_DIR", "ROUNDTABLE_HOME", "ROUNDTABLE_INSTANCE_NAME")
            }
            env.update(PYTHONPATH=str(ROOT), XDG_STATE_HOME=str(Path(temp) / "private-state"))
            code = 'from state_paths import state_dir; print(state_dir(platform="linux"))'
            first = subprocess.check_output(
                [sys.executable, "-c", code], cwd=ROOT, env=env, text=True
            )
            second = subprocess.check_output(
                [sys.executable, "-c", code], cwd=temp, env=env, text=True
            )
            self.assertEqual(first, second)

    def test_protected_and_legacy_warnings_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp).resolve()
            code = home / "Documents" / "code"
            (code / "data/local").mkdir(parents=True)
            (code / "data/local/secret").symlink_to(home / "not-readable")
            warnings = path_warnings(home / "Desktop/state", code, platform="darwin", home=home)
            self.assertIn("state_in_macos_protected_directory", warnings)
            self.assertIn("code_in_macos_protected_directory", warnings)
            self.assertIn("legacy_state_detected_manual_transfer_see_STORAGE", warnings)
            self.assertIn(
                "state_inside_checkout_migrate_recommended",
                path_warnings(code / "data/local", code, platform="darwin", home=home),
            )


class Maintenance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.source = runtime.private_dir(self.base / "old & instance")
        self.target = self.base / "new state"
        self.args = argparse.Namespace(
            origin="grok", worker="dot", allowance=1, server_port=None, mcp_port=None, name="new"
        )
        runtime.setup(self.source, self.args)
        self.config = runtime.load(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def test_live_pid_and_reused_pid_refused_without_signals(self):
        runtime.write_json(
            self.source / "server.pid.json",
            {"pid": 123, "stamp": "synthetic-stamp", "identity": self.config["identity"]},
        )
        with (
            patch.object(runtime, "process_stamp", return_value="synthetic-stamp"),
            patch.object(os, "kill", side_effect=AssertionError),
        ):
            with self.assertRaisesRegex(runtime.Failure, "instance_running_use_down"):
                require_stopped(self.source, self.config, runtime)
        with (
            patch.object(runtime, "process_stamp", return_value="different-stamp"),
            patch.object(os, "kill", side_effect=AssertionError),
        ):
            require_stopped(self.source, self.config, runtime)
        self.assertFalse((self.source / "server.pid.json").exists())
        self.assertTrue(any((self.source / "reaped-cleanup").glob("*-server.pid.json")))
        self.assertFalse(self.target.exists())

    def test_dead_pid_without_stop_is_reaped(self):
        runtime.write_json(
            self.source / "server.pid.json",
            {"pid": 123, "stamp": "synthetic", "identity": self.config["identity"]},
        )
        with patch.object(runtime, "process_stamp", return_value=""):
            require_stopped(self.source, self.config, runtime)
        self.assertFalse((self.source / "server.pid.json").exists())
        self.assertTrue(any((self.source / "reaped-cleanup").glob("*-server.pid.json")))
        self.assertFalse(self.target.exists())

    def test_unclean_descendant_and_occupied_port_refused(self):
        runtime.write_json(self.source / "mcp.started.json", {"identity": self.config["identity"]})
        require_stopped(self.source, self.config, runtime)
        self.assertFalse((self.source / "mcp.started.json").exists())
        self.assertTrue(any((self.source / "reaped-cleanup").glob("*-mcp.started.json")))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            self.config["server_port"] = sock.getsockname()[1]
            with self.assertRaisesRegex(runtime.Failure, "port_in_use"):
                require_stopped(self.source, self.config, runtime)

    def test_rebind_and_stable_launchd_wrapper(self):
        old = dict(self.config, home="/old/synthetic/checkout")
        runtime.write_json(self.source / "instance.json", old, replace=True)
        self.assertEqual(runtime.load(self.source)["home"], old["home"])
        output = io.StringIO()
        with (
            patch.object(
                sys, "argv", ["local_runtime.py", "rebind", "--state-dir", str(self.source)]
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(runtime.main(), 0)
        self.assertEqual(runtime.load(self.source)["home"], str(runtime.HOME))
        runtime.render(self.source, self.base / "plists")
        for file in (self.base / "plists").glob("*.plist"):
            command = plistlib.loads(file.read_bytes())["ProgramArguments"]
            self.assertEqual(command[:2], ["/bin/sh", str(ROOT / "scripts/up.sh")])
            self.assertNotIn(sys.executable, command)

    def test_auto_ports_distinct_explicit_preserved_and_named_config(self):
        self.assertNotEqual(self.config["server_port"], self.config["mcp_port"])
        self.assertEqual(self.config["name"], "new")
        other = runtime.private_dir(self.base / "other")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        args = argparse.Namespace(
            origin="grok", worker="dot", allowance=1, server_port=port, mcp_port=None, name="other"
        )
        runtime.setup(other, args)
        self.assertEqual(runtime.load(other)["server_port"], port)
        self.assertNotEqual(runtime.load(other)["identity"], self.config["identity"])


class Logs(unittest.TestCase):
    def test_rotation_private_bounded_and_single_writer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            file = root / "logs/server.log"
            with RotatingLog(file, 256, 3) as log:
                with self.assertRaises(BlockingIOError):
                    with RotatingLog(file, 256, 3):
                        pass
                for _ in range(100):
                    log.write("component_started\n")
                log.flush()
            files = [p for p in file.parent.iterdir() if not p.name.endswith(".lock")]
            self.assertEqual(len(files), 4)
            for p in files:
                self.assertLessEqual(p.stat().st_size, 256)
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_rotation_rejects_backup_symlink_and_drops_oversize(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            file = root / "server.log"
            with RotatingLog(file, 256, 2) as log:
                log.write("x" * 300)
                self.assertNotIn("xxx", file.read_text())
                (root / "server.log.1").symlink_to(file)
                with self.assertRaises(credentials.CredentialError):
                    log.write("x" * 256)


if __name__ == "__main__":
    unittest.main()
