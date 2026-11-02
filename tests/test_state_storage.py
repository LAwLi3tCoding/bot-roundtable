"""Platform paths and stopped-instance migration, entirely synthetic and temporary."""

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
from unittest.mock import Mock, patch

import admin_credentials as credentials
from private_logs import RotatingLog
from state_paths import state_dir, log_dir, path_warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import local_runtime as runtime  # noqa: E402
from state_migration import migrate_state, require_stopped  # noqa: E402


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
            self.assertIn("legacy_state_detected_use_migrate_state", warnings)
            self.assertIn(
                "state_inside_checkout_migrate_recommended",
                path_warnings(code / "data/local", code, platform="darwin", home=home),
            )


class Migration(unittest.TestCase):
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

    def test_verified_migration_idempotence_private_and_source_retained(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir() if p.is_file()}
        result = migrate_state(self.source, self.target, self.args, runtime)
        self.assertFalse(result["already_migrated"])
        self.assertTrue(result["source_retained"])
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.source.iterdir() if p.is_file()}
        )
        self.assertTrue(
            migrate_state(self.source, self.target, self.args, runtime)["already_migrated"]
        )
        for p in self.target.iterdir():
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o700)
        runtime.load(self.target)
        self.assertEqual(
            credentials.get_admin_token(self.source, environ={}),
            credentials.get_admin_token(self.target, environ={}),
        )

    def test_source_or_target_difference_not_idempotent_success(self):
        migrate_state(self.source, self.target, self.args, runtime)
        runtime.save(self.target / "unrelated.json", "{}")
        with self.assertRaisesRegex(runtime.Failure, "target_mismatch"):
            migrate_state(self.source, self.target, self.args, runtime)
        (self.target / "unrelated.json").unlink()
        runtime.save(self.source / "new.json", "{}")
        with self.assertRaisesRegex(runtime.Failure, "target_mismatch"):
            migrate_state(self.source, self.target, self.args, runtime)

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
                migrate_state(self.source, self.target, self.args, runtime)
        with patch.object(runtime, "process_stamp", return_value="different-stamp"):
            with self.assertRaisesRegex(runtime.Failure, "identity_uncertain"):
                migrate_state(self.source, self.target, self.args, runtime)
        self.assertFalse(self.target.exists())

    def test_dead_pid_without_stop_is_uncertain(self):
        runtime.write_json(
            self.source / "server.pid.json",
            {"pid": 123, "stamp": "synthetic", "identity": self.config["identity"]},
        )
        with (
            patch.object(runtime, "process_stamp", return_value=""),
            self.assertRaisesRegex(runtime.Failure, "cleanup_unconfirmed"),
        ):
            migrate_state(self.source, self.target, self.args, runtime)
        self.assertFalse(self.target.exists())

    def test_unclean_descendant_and_occupied_port_refused(self):
        runtime.write_json(self.source / "mcp.started.json", {"identity": self.config["identity"]})
        with self.assertRaisesRegex(runtime.Failure, "cleanup_unconfirmed"):
            require_stopped(self.source, self.config, runtime)
        (self.source / "mcp.started.json").unlink()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            self.config["server_port"] = sock.getsockname()[1]
            with self.assertRaisesRegex(runtime.Failure, "port_in_use"):
                require_stopped(self.source, self.config, runtime)

    def test_shared_lifecycle_lock_prevents_copy(self):
        with runtime.locked(self.source), self.assertRaises(BlockingIOError):
            migrate_state(self.source, self.target, self.args, runtime)
        self.assertFalse(self.target.exists())

    def test_symlink_wal_and_unsafe_permissions_refused(self):
        (self.source / "extra.json").symlink_to(self.source / "instance.json")
        with self.assertRaises(credentials.CredentialError):
            migrate_state(self.source, self.target, self.args, runtime)
        (self.source / "extra.json").unlink()
        runtime.save(self.source / "roundtable.db-wal", "")
        with self.assertRaisesRegex(runtime.Failure, "checkpointed"):
            migrate_state(self.source, self.target, self.args, runtime)
        (self.source / "roundtable.db-wal").unlink()
        (self.source / "grok.env").chmod(0o644)
        with self.assertRaises(credentials.CredentialError):
            migrate_state(self.source, self.target, self.args, runtime)

    def test_partial_failure_removes_only_own_staging(self):
        original = runtime.write_json

        def fail(path, value, replace=False):
            if Path(path).name == "migration.json":
                raise OSError("synthetic-secret-error")
            return original(path, value, replace)

        with patch.object(runtime, "write_json", side_effect=fail), self.assertRaises(OSError):
            migrate_state(self.source, self.target, self.args, runtime)
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.base.glob(".migrate-*")))
        self.assertTrue((self.source / "instance.json").exists())

    def test_source_change_during_copy_rolls_back(self):
        import state_migration

        original = state_migration.fingerprint
        changed = False

        def changing(path, destination=None):
            nonlocal changed
            result = original(path, destination)
            if destination is not None and not changed:
                changed = True
                runtime.save(self.source / "grok.env", "synthetic changed content", replace=True)
            return result

        with (
            patch.object(state_migration, "fingerprint", side_effect=changing),
            self.assertRaisesRegex(runtime.Failure, "changed|verification_failed"),
        ):
            migrate_state(self.source, self.target, self.args, runtime)
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.base.glob(".migrate-*")))

    def test_source_replaced_with_fifo_does_not_block(self):
        import state_migration

        pipe = self.source / "replacement"
        os.mkfifo(pipe, 0o600)
        # Simulate the object changing after the initial path check.
        with (
            patch.object(state_migration, "check_private"),
            self.assertRaisesRegex(runtime.Failure, "private_file_required"),
        ):
            state_migration.fingerprint(pipe)

    def test_source_ancestor_swap_is_not_followed(self):
        from state_migration import open_pinned

        real = runtime.private_dir(self.base / "real-directory")
        runtime.save(real / "file", "synthetic")
        (self.base / "alias").symlink_to(real, target_is_directory=True)
        with self.assertRaises(OSError):
            open_pinned(self.base / "alias/file")

    def test_explicit_migration_source_required(self):
        output = io.StringIO()
        with (
            patch.object(
                sys, "argv", ["local_runtime.py", "migrate-state", "--state-dir", str(self.target)]
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(runtime.main(), 1)
        self.assertIn("migration_explicit_source_required", output.getvalue())
        self.assertFalse(self.target.exists())

    def test_keyring_metadata_reuses_entry_without_secret_store_write(self):
        binding = credentials.account(self.source)
        runtime.write_json(
            self.source / "admin.json",
            {"version": 1, "backend": "keyring", "account": binding},
            replace=True,
        )
        with patch.object(
            credentials,
            "trusted_keyring",
            side_effect=AssertionError("no keyring access during migration"),
        ):
            migrate_state(self.source, self.target, self.args, runtime)
        backend = Mock()
        backend.get_password.return_value = "synthetic" * 8
        with patch.object(credentials, "trusted_keyring", return_value=backend):
            self.assertEqual(credentials.get_admin_token(self.target, environ={}), "synthetic" * 8)
        backend.get_password.assert_called_once_with(credentials.SERVICE, binding)
        backend.set_password.assert_not_called()

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
