"""Synthetic old layouts and explicit maintenance operations, no live accounts."""

import argparse
import contextlib
import io
import subprocess
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import admin_credentials as credentials
from roundtable import digest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import local_runtime as runtime  # noqa: E402
from sqlite_maintenance import checkpoint_state  # noqa: E402


def hashes(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


class Rework(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.state = runtime.private_dir(self.root / "instance")
        self.args = argparse.Namespace(
            origin="grok",
            worker="dot",
            allowance=1,
            server_port=None,
            mcp_port=None,
            name="synthetic",
        )
        runtime.setup(self.state, self.args)
        self.config = runtime.load(self.state)

    def tearDown(self):
        self.temp.cleanup()

    def test_checkpoint_closed_copy_leaves_no_wal(self):
        live = runtime.private_dir(self.root / "writer")
        runtime.save(live / "sample.db", "")
        conn = sqlite3.connect(live / "sample.db")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE sample(value)")
        conn.execute("INSERT INTO sample VALUES(1)")
        conn.commit()
        closed = runtime.private_dir(self.root / "closed")
        for path in live.glob("sample.db*"):
            shutil.copy2(path, closed / path.name)
        conn.close()
        self.assertTrue((closed / "sample.db-wal").exists())
        checkpoint_state(closed)
        self.assertFalse((closed / "sample.db-wal").exists())
        with sqlite3.connect(closed / "sample.db") as checked:
            self.assertEqual(checked.execute("SELECT value FROM sample").fetchone()[0], 1)

    def test_room_env_missing_requires_explicit_rotation_or_recovery(self):
        old = runtime.env_read(self.state / "room.env")["ROUNDTABLE_ROOM_TOKEN"]
        (self.state / "room.env").unlink()
        result = runtime.setup(self.state, self.args)
        self.assertFalse(result["room_env"]["ok"])
        self.assertFalse((self.state / "room.env").exists())
        self.assertTrue(
            runtime.repair_room_env(self.state, self.config, rotate=True)["rotated_room_owner"]
        )
        new = runtime.env_read(self.state / "room.env")["ROUNDTABLE_ROOM_TOKEN"]
        self.assertNotEqual(old, new)
        with sqlite3.connect(self.state / "roundtable.db") as db:
            self.assertEqual(db.execute("SELECT token FROM rooms").fetchone()[0], digest(new))
        (self.state / "room.env").unlink()
        runtime.write_json(
            self.state / "admin.json",
            {
                "version": 1,
                "backend": "file",
                "token": "a" * 48,
                "room": self.config["room"],
                "room_token": new,
            },
            replace=True,
        )
        self.assertTrue(runtime.repair_room_env(self.state, self.config)["recovered"])

    def test_up_write_down_checkpoints_all_managed_databases(self):
        def command(action, *extra):
            output = io.StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    ["local_runtime.py", action, "--state-dir", str(self.state), *extra],
                ),
                contextlib.redirect_stdout(output),
            ):
                status = runtime.main()
            self.assertEqual(status, 0, output.getvalue())
            return json.loads(output.getvalue())

        with patch.dict(os.environ, {key: "" for key in runtime.AMBIENT}):
            try:
                command("up", "--without-tunnel", "--no-caffeinate")
                runtime.request(
                    self.config["server_port"],
                    "/api/bots",
                    credentials.get_admin_token(self.state, environ={}),
                    {"id": "written-bot", "name": "Written", "kind": "mailbox"},
                )
                # Synthetic abrupt writer leaves WAL on a separate managed ledger.
                for name in ("terminal.db", "terminal-receipts.db"):
                    subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "import sqlite3,os,sys; os.umask(0o077); db=sqlite3.connect(sys.argv[1]); db.execute('PRAGMA journal_mode=WAL'); db.execute('CREATE TABLE marker(value)'); db.execute('INSERT INTO marker VALUES(1)'); db.commit(); os._exit(0)",
                            str(self.state / name),
                        ],
                        check=True,
                    )
                self.assertTrue(list(self.state.glob("*-wal")))
                result = command("down")
                self.assertGreaterEqual(result["checkpointed_databases"], 3)
                self.assertFalse(list(self.state.glob("*-wal")))
            finally:
                for component in ("tunnel", "mcp", "server"):
                    runtime.stop_component(self.state, self.config, component)

    def test_missing_configuration_has_complete_setup_hint(self):
        selected = self.root / "not-configured"
        for action in ("up", "down", "ui", "client", "status", "doctor"):
            output = io.StringIO()
            with (
                patch.object(
                    sys, "argv", ["local_runtime.py", action, "--state-dir", str(selected)]
                ),
                contextlib.redirect_stdout(output),
            ):
                status = runtime.main()
            result = json.loads(output.getvalue())
            self.assertEqual(status, 0 if action in ("status", "doctor") else 1)
            self.assertEqual(result["reason"], "not_configured_run_setup")
            self.assertIn(
                str(ROOT / "scripts/setup-local.py"), shlex.split(result["setup_command"])
            )
            self.assertIn(str(selected), shlex.split(result["setup_command"]))
            self.assertFalse(selected.exists())

    def test_path_error_reason_is_safe_and_specific(self):
        cases = [
            ("invalid_instance_name", ["--name", "../secret"], None),
            ("xdg_state_home_must_be_absolute", [], "linux"),
            ("localappdata_required", [], "win32"),
        ]
        for reason, args, platform in cases:
            output = io.StringIO()
            with (
                patch.dict(os.environ, {"XDG_STATE_HOME": "relative-sensitive-value"}, clear=True),
                patch.object(sys, "argv", ["local_runtime.py", "paths", *args]),
                patch("state_paths.sys.platform", platform or "darwin"),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(runtime.main(), 1)
            result = json.loads(output.getvalue())
            self.assertEqual(result["reason"], reason)
            self.assertEqual(result["error_type"], "StatePathError")
            self.assertNotIn("relative-sensitive-value", output.getvalue())
            self.assertNotIn("../secret", output.getvalue())

    def test_manual_database_default_is_separate_even_with_state_override(self):
        from state_paths import state_dir, manual_state_dir

        for platform in ("darwin", "linux", "win32"):
            env = {"ROUNDTABLE_STATE_DIR": str(self.root / "shared-root")}
            managed = state_dir(environ=env, platform=platform)
            manual = manual_state_dir(environ=env, platform=platform)
            self.assertEqual(manual, managed / "manual")
            self.assertNotEqual(managed / "roundtable.db", manual / "roundtable.db")
        import server

        selected = self.root / "manual-cli-root"
        env = {"ROUNDTABLE_STATE_DIR": str(selected)}
        for explicit in (False, True):
            database = selected / ("custom.db" if explicit else "manual/roundtable.db")
            argv = ["server.py", *(["--db", str(database)] if explicit else [])]
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(sys, "argv", argv),
                patch.object(
                    server, "Store", side_effect=RuntimeError("test-stop-before-server")
                ) as store,
                patch.object(
                    credentials, "get_admin_token", return_value="synthetic"
                ) as credential,
            ):
                with self.assertRaisesRegex(RuntimeError, "test-stop-before-server"):
                    server.main()
                store.assert_called_once_with(str(database), demo=False)
                self.assertEqual(
                    Path(credential.call_args.args[0]), database.parent / "admin-credentials"
                )
        output = io.StringIO()
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(sys, "argv", ["admin_credentials.py", "rotate-admin-token"]),
            patch.object(credentials, "rotate_admin_token", return_value={"ok": True}) as rotate,
            contextlib.redirect_stdout(output),
        ):
            credentials.main()
            self.assertEqual(Path(rotate.call_args.args[0]), selected / "manual/admin-credentials")
        self.assertIn("manual_state_dir()", (ROOT / "scripts/start-local.sh").read_text())

    def test_detected_legacy_directory_points_to_manual_storage_guide(self):
        checkout = self.root / "synthetic-checkout"
        (checkout / "data/local").mkdir(parents=True)
        selected = self.root / "new-default"
        output = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(runtime, "HOME", checkout),
            patch.object(runtime, "state_dir", return_value=selected),
            patch.object(sys, "argv", ["local_runtime.py", "setup"]),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(runtime.main(), 1)
        self.assertEqual(
            json.loads(output.getvalue())["reason"],
            "legacy_state_detected_manual_transfer_see_STORAGE",
        )
        self.assertFalse(selected.exists())

    def test_checkpoint_refuses_open_database_without_mutating_it(self):
        db = sqlite3.connect(self.state / "roundtable.db")
        try:
            db.execute("SELECT id FROM rooms").fetchall()
            before = (self.state / "roundtable.db").read_bytes()
            with self.assertRaisesRegex(runtime.Failure, "database_in_use_stop_instance"):
                checkpoint_state(self.state)
            self.assertEqual(before, (self.state / "roundtable.db").read_bytes())
        finally:
            db.close()

    def test_pending_room_token_wrong_binding_refused_without_mutation(self):
        (self.state / "room.env").unlink()
        runtime.env_save(
            self.state / "room-token.pending.env",
            {"ROUNDTABLE_ROOM": "0" * 24, "ROUNDTABLE_ROOM_TOKEN": "x" * 43},
        )
        before = hashes(self.state)
        with self.assertRaisesRegex(runtime.Failure, "invalid_pending_room_token_binding"):
            runtime.repair_room_env(self.state, self.config, rotate=True)
        self.assertEqual(before, hashes(self.state))

    def test_pending_routine_approval_no_dispatch(self):
        env = {
            "GROK_ROUTINE_URL": "https://routine.example.com/hook",
            "GROK_ROUTINE_KEY": "synthetic",
            "GROK_ALLOWED_HOST": "routine.example.com",
        }
        runtime.write_json(
            self.state / "routine.pending.json", {"environment": env, "explicit_opt_in": False}
        )
        with patch(
            "grok_adapter.GrokWebhook.dispatch_terminal", side_effect=AssertionError("no dispatch")
        ):
            self.assertTrue(runtime.approve_routine(self.state, self.config)["approved"])
        self.assertTrue(runtime.read_json(self.state / "routine.json")["explicit_opt_in"])
        with self.assertRaisesRegex(runtime.Failure, "already_configured"):
            runtime.approve_routine(self.state, self.config)

    def test_next_steps_complete_and_diagnostics_override(self):
        for command in runtime.next_steps(self.state):
            words = shlex.split(command)
            self.assertEqual(words[0], sys.executable)
            self.assertEqual(words[1], str(ROOT / "scripts/local_runtime.py"))
            self.assertIn(str(self.state), words)
        with patch.dict(os.environ, {"ROUNDTABLE_ADMIN_TOKEN": "synthetic-override-" + "x" * 40}):
            report = runtime.diagnostics(self.state, self.config)
        self.assertTrue(report["admin_environment_override_active"])
        self.assertNotIn("synthetic-override", json.dumps(report))
        self.assertNotEqual(runtime.Failure.__name__, "CredentialError")

    def test_ui_issue_and_open_never_returns_code_or_admin(self):
        code = "x" * 43
        with (
            patch.object(runtime, "owned", return_value=123),
            patch.object(runtime, "ready", return_value=True),
            patch.object(runtime.sys, "platform", "darwin"),
            patch.object(runtime.shutil, "which", return_value="open"),
            patch.object(runtime, "get_admin_token", return_value="synthetic-admin"),
            patch.object(
                runtime, "request", return_value={"code": code, "expires_in": 60}
            ) as request,
            patch.object(runtime.subprocess, "run") as run,
        ):
            result = runtime.open_ui(self.state, self.config)
            request.assert_called_once_with(
                self.config["server_port"], "/api/ui-login/issue", "synthetic-admin", {}
            )
            self.assertIn("#roundtable-login=", run.call_args.args[0][-1])
            self.assertNotIn("synthetic-admin", str(run.call_args))
            self.assertNotIn(code, json.dumps(result))

    def test_keyring_rotation_deletes_old_only_after_publication(self):
        state = runtime.private_dir(self.root / "keyring")
        values = {}
        backend = Mock()
        backend.get_password.side_effect = lambda service, name: values.get(name)
        backend.set_password.side_effect = lambda service, name, value: values.__setitem__(
            name, value
        )
        backend.delete_password.side_effect = lambda service, name: values.pop(name)
        with patch.object(credentials, "trusted_keyring", return_value=backend):
            first = credentials.get_admin_token(state, prefer_keyring=True, environ={})
            result = credentials.rotate_admin_token(state, environ={})
            self.assertEqual(result["old_keyring_entry"], "deleted")
            self.assertNotIn(first, values.values())
            self.assertNotEqual(first, credentials.get_admin_token(state, environ={}))

    def test_keyring_cleanup_failure_keeps_published_rotation(self):
        state = runtime.private_dir(self.root / "keyring-cleanup")
        values = {}
        backend = Mock()
        backend.get_password.side_effect = lambda service, name: values.get(name)
        backend.set_password.side_effect = lambda service, name, value: values.__setitem__(
            name, value
        )
        backend.delete_password.side_effect = RuntimeError("synthetic-sensitive-error")
        with patch.object(credentials, "trusted_keyring", return_value=backend):
            old = credentials.get_admin_token(state, prefer_keyring=True, environ={})
            report = credentials.rotate_admin_token(state, environ={})
            self.assertEqual(report["old_keyring_entry"], "failed_manual_cleanup_required")
            self.assertNotEqual(old, credentials.get_admin_token(state, environ={}))
            self.assertNotIn("synthetic-sensitive-error", json.dumps(report))
            backend.delete_password.reset_mock()
            before = credentials.get_admin_token(state, environ={})
            with patch.object(
                credentials,
                "persist",
                side_effect=credentials.CredentialError("publication_failed"),
            ):
                with self.assertRaises(credentials.CredentialError):
                    credentials.rotate_admin_token(state, environ={})
            backend.delete_password.assert_not_called()
            self.assertEqual(before, credentials.get_admin_token(state, environ={}))


if __name__ == "__main__":
    unittest.main()
