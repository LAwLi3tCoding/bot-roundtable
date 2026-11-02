"""Synthetic old layouts and explicit maintenance operations, no live accounts."""

import argparse
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
from roundtable import Store, digest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import local_runtime as runtime  # noqa: E402
from legacy_import import import_legacy  # noqa: E402
from sqlite_snapshot import backup_readonly, checkpoint_state  # noqa: E402


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

    def test_combined_admin_named_members_and_wal_snapshot_unchanged(self):
        old = runtime.private_dir(self.root / "old")
        live = runtime.private_dir(self.root / "fixture")
        runtime.save(live / "roundtable.db", "")
        db = Store(str(live / "roundtable.db"))
        for name in ("grok-local-test", "dot-local-test"):
            db.register_bot(name, name, "mailbox")
        room = db.create_group("Synthetic", ["grok-local-test", "dot-local-test"])
        runtime.write_json(
            old / "admin.json",
            {"ROUNDTABLE_ADMIN_TOKEN": "a" * 48, "room": room["id"], "room_token": room["token"]},
        )
        for agent in room["agent_tokens"]:
            runtime.write_json(
                old / (agent["id"] + ".json"),
                {
                    "ROUNDTABLE_AGENT": agent["id"],
                    "ROUNDTABLE_ROOM": room["id"],
                    "ROUNDTABLE_TOKEN": agent["token"],
                },
            )
        for path in live.glob("roundtable.db*"):
            shutil.copy2(path, old / path.name)
        db.db.close()
        self.assertTrue((old / "roundtable.db-wal").exists())
        before = hashes(old)
        args = argparse.Namespace(
            origin="grok",
            worker="dot",
            server_port=self.config["server_port"],
            mcp_port=self.config["mcp_port"],
            proxy=None,
        )
        target = runtime.private_dir(self.root / "imported")
        result = import_legacy(str(old), target, args, runtime)
        self.assertTrue(result["history_imported"])
        self.assertEqual(before, hashes(old))
        imported = runtime.load(target)
        self.assertEqual(imported["origin"], "grok-local-test")
        self.assertEqual(imported["worker"], "dot-local-test")

    def test_open_source_database_refused(self):
        store = Store(str(self.state / "roundtable.db"))
        destination = self.root / "backup.db"
        try:
            with self.assertRaisesRegex(runtime.Failure, "database_in_use"):
                backup_readonly(self.state / "roundtable.db", destination)
        finally:
            store.db.close()
        self.assertFalse(destination.exists())

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
