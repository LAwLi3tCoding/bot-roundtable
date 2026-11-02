"""Synthetic credentials only; never accesses an OS credential store or clipboard."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import admin_credentials as credentials

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import local_runtime as runtime  # noqa: E402
from legacy_import import import_legacy, parse_env  # noqa: E402


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name).resolve() / "credentials"

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_environment_override_and_rotation(self):
        first = credentials.get_admin_token(self.state, environ={})
        self.assertEqual(first, credentials.get_admin_token(self.state, environ={}))
        before = (self.state / "admin.json").read_bytes()
        override = "synthetic+/=" * 5
        self.assertEqual(
            override,
            credentials.get_admin_token(self.state, environ={"ROUNDTABLE_ADMIN_TOKEN": override}),
        )
        self.assertEqual(before, (self.state / "admin.json").read_bytes())
        with self.assertRaisesRegex(credentials.CredentialError, "override_active"):
            credentials.rotate_admin_token(self.state, environ={"ROUNDTABLE_ADMIN_TOKEN": override})
        result = credentials.rotate_admin_token(self.state, environ={})
        self.assertNotEqual(first, credentials.get_admin_token(self.state, environ={}))
        self.assertNotIn(first, json.dumps(result))
        self.assertEqual((self.state / "admin.json").stat().st_mode & 0o777, 0o600)

    def test_override_does_not_create_files(self):
        credentials.get_admin_token(self.state, environ={"ROUNDTABLE_ADMIN_TOKEN": "x" * 40})
        self.assertFalse(self.state.exists())

    def test_keyring_unavailable_fallback_and_existing_fail_closed(self):
        with patch.object(credentials, "trusted_keyring", return_value=None):
            credentials.get_admin_token(self.state, prefer_keyring=True, environ={})
        self.assertEqual(json.loads((self.state / "admin.json").read_text())["backend"], "file")
        credentials.save_private(
            self.state / "admin.json",
            json.dumps(
                {"version": 1, "backend": "keyring", "account": credentials.account(self.state)}
            ),
            True,
        )
        before = (self.state / "admin.json").read_bytes()
        with (
            patch.object(credentials, "trusted_keyring", return_value=None),
            self.assertRaisesRegex(credentials.CredentialError, "keyring_unavailable"),
        ):
            credentials.get_admin_token(self.state, environ={})
        self.assertEqual(before, (self.state / "admin.json").read_bytes())

    def test_keyring_write_failure_never_falls_back(self):
        backend = Mock()
        backend.get_password.return_value = None
        backend.set_password.side_effect = RuntimeError("synthetic-secret")
        with (
            patch.object(credentials, "trusted_keyring", return_value=backend),
            self.assertRaisesRegex(credentials.CredentialError, "keyring_write_failed"),
        ):
            credentials.get_admin_token(self.state, prefer_keyring=True, environ={})
        self.assertFalse((self.state / "admin.json").exists())

    def test_mock_keyring_persists_and_rotates_without_value_output(self):
        values = {}
        backend = Mock()
        backend.get_password.side_effect = lambda service, name: values.get(name)
        backend.set_password.side_effect = lambda service, name, value: values.__setitem__(
            name, value
        )
        with patch.object(credentials, "trusted_keyring", return_value=backend):
            first = credentials.get_admin_token(self.state, prefer_keyring=True, environ={})
            self.assertEqual(first, credentials.get_admin_token(self.state, environ={}))
            credentials.rotate_admin_token(self.state, environ={})
            self.assertNotEqual(first, credentials.get_admin_token(self.state, environ={}))
        self.assertNotIn(first, (self.state / "admin.json").read_text())

    def test_windows_acl_failure_prevents_secret_write(self):
        with (
            patch.object(credentials, "WINDOWS", True),
            patch.object(
                credentials,
                "windows_acl",
                side_effect=credentials.CredentialError("private_acl_unavailable"),
            ),
        ):
            with self.assertRaises(credentials.CredentialError):
                credentials.get_admin_token(self.state, environ={})
        self.assertFalse((self.state / "admin.json").exists())
        self.assertFalse(list(self.state.glob(".*.????????????????")))

    def test_windows_acl_checked_before_any_secret_bytes(self):
        self.state.mkdir(mode=0o700)
        seen = []

        def acl(path, create=False):
            path = Path(path)
            if path.is_file():
                self.assertEqual(path.read_bytes(), b"")
                self.assertTrue(create)
                seen.append(path)

        with (
            patch.object(credentials, "WINDOWS", True),
            patch.object(credentials, "windows_acl", side_effect=acl),
        ):
            credentials.save_private(self.state / "private", "synthetic-secret")
        self.assertEqual(len(seen), 1)
        self.assertEqual((self.state / "private").read_text(), "synthetic-secret")

    def test_acl_diagnostics_never_forward_raw_output(self):
        with patch.object(
            credentials.subprocess,
            "run",
            return_value=Mock(returncode=1, stdout="synthetic-secret"),
        ):
            with self.assertRaisesRegex(credentials.CredentialError, "^private_acl_unavailable$"):
                credentials.windows_acl(self.state)

    def test_keyring_disappearing_during_rotation_never_downgrades(self):
        values = {}
        backend = Mock()
        backend.get_password.side_effect = lambda service, name: values.get(name)
        backend.set_password.side_effect = lambda service, name, value: values.__setitem__(
            name, value
        )
        with patch.object(credentials, "trusted_keyring", return_value=backend):
            credentials.get_admin_token(self.state, prefer_keyring=True, environ={})
        before = (self.state / "admin.json").read_bytes()
        with (
            patch.object(credentials, "trusted_keyring", side_effect=[backend, None]),
            self.assertRaisesRegex(credentials.CredentialError, "keyring_unavailable"),
        ):
            credentials.rotate_admin_token(self.state, environ={})
        self.assertEqual(before, (self.state / "admin.json").read_bytes())

    def test_junction_and_symlink_rejected(self):
        with (
            patch.object(Path, "is_junction", return_value=True),
            self.assertRaisesRegex(credentials.CredentialError, "symlink"),
        ):
            credentials.private_directory(self.state)
        real = credentials.private_directory(self.state)
        credentials.save_private(real / "file", "synthetic")
        (real / "link").symlink_to(real / "file")
        with self.assertRaises(credentials.CredentialError):
            credentials.read_private(real / "link")

    def test_parallel_first_start(self):
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=6) as pool:
            values = list(
                pool.map(lambda _: credentials.get_admin_token(self.state, environ={}), range(12))
            )
        self.assertEqual(len(set(values)), 1)


class RuntimeContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = runtime.private_dir(Path(self.temp.name).resolve() / "state")

    def tearDown(self):
        self.temp.cleanup()

    def test_real_managed_origin_create_tasks_inbox_and_stalled_stdin(self):
        from roundtable import Store
        from server import make_server
        import threading

        store = Store()
        for agent in ("grok", "dot"):
            store.register_bot(agent, agent, "mailbox")
        room = store.create_group("Synthetic", ["grok", "dot"])
        store.grant(room["id"], "grok", 2)
        server = make_server(store, "a" * 48, port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        token = next(a["token"] for a in room["agent_tokens"] if a["id"] == "grok")
        runtime.env_save(
            self.state / "grok.env",
            {"ROUNDTABLE_URL": f"http://127.0.0.1:{server.server_port}", "ROUNDTABLE_TOKEN": token},
        )
        config = {"room": room["id"], "origin": "grok", "worker": "dot"}
        args = argparse.Namespace(operation="create", task_id=None, body=None)
        payload = {
            "title": "Synthetic",
            "context": "Read only",
            "assignments": [{"worker": "dot", "instruction": "Report only"}],
            "request_id": "managed-create",
            "budget": 1,
        }
        try:
            with patch("local_client.read_json_stdin", return_value=payload):
                created = runtime.run_client(self.state, config, args)
            args.operation = "tasks"
            tasks = runtime.run_client(self.state, config, args)
            self.assertIn(created["task_id"], json.dumps(tasks))
            args.operation = "inbox"
            inbox = runtime.run_client(self.state, config, args)
            self.assertNotIn(token, json.dumps(inbox))
            self.assertEqual(store.db.execute("SELECT origin FROM tasks").fetchone()[0], "bot:grok")
            # Exercise the shared reader through local_client, keeping the pipe open.
            command = [sys.executable, str(ROOT / "local_client.py"), "create"]
            env = dict(
                os.environ,
                ROUNDTABLE_URL=f"http://127.0.0.1:{server.server_port}",
                ROUNDTABLE_ROOM=room["id"],
                ROUNDTABLE_AGENT="grok",
                ROUNDTABLE_TOKEN=token,
            )
            with subprocess.Popen(
                command,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as child:
                self.assertEqual(child.wait(timeout=5), 1)
                self.assertNotIn(token.encode(), child.stdout.read() + child.stderr.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.db.close()

    def test_ui_mock_clipboard_no_secret_arguments(self):
        config = {"server_port": 12345}
        for platform, binary in (("darwin", "pbcopy"), ("linux", "wl-copy"), ("win32", "clip.exe")):
            with (
                patch.object(runtime.sys, "platform", platform),
                patch.object(runtime.shutil, "which", return_value=binary),
                patch.object(runtime, "get_admin_token", return_value="synthetic-private-value"),
                patch.object(runtime.subprocess, "run") as run,
            ):
                result = runtime.open_ui(self.state, config, copy_token=True)
                self.assertEqual(run.call_args.args[0], [binary])
                self.assertNotIn("synthetic-private-value", str(run.call_args.args))
                self.assertNotIn("synthetic-private-value", json.dumps(result))
        with (
            patch.object(runtime.shutil, "which", return_value=None),
            patch.object(runtime, "get_admin_token", side_effect=AssertionError),
        ):
            self.assertFalse(
                runtime.open_ui(self.state, config, copy_token=True)["clipboard_copied"]
            )

    def test_ui_clipboard_failure_does_not_open(self):
        with (
            patch.object(runtime.sys, "platform", "darwin"),
            patch.object(runtime.shutil, "which", return_value="pbcopy"),
            patch.object(runtime, "get_admin_token", return_value="synthetic"),
            patch.object(
                runtime.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "pbcopy")
            ) as run,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                runtime.open_ui(self.state, {"server_port": 12345}, copy_token=True)
            self.assertEqual(run.call_count, 1)

    def test_preflight_diagnostics(self):
        with self.assertRaisesRegex(runtime.Failure, "runtime_key_missing"):
            runtime.preflight_tunnel(self.state)
        runtime.save(
            self.state / "runtime-key.env", "CONTROL_PLANE_API_KEY=sk-synthetic-test-value\n"
        )
        with (
            patch.object(runtime.shutil, "which", return_value=None),
            self.assertRaisesRegex(runtime.Failure, "tunnel_client_not_found"),
        ):
            runtime.preflight_tunnel(self.state)
        runtime.save(self.state / "tunnel.yaml", (ROOT / "examples/tunnel-client.yaml").read_text())
        with (
            patch.object(runtime.shutil, "which", return_value="/synthetic/bin/tunnel-client"),
            self.assertRaisesRegex(runtime.Failure, "tunnel_id_placeholder"),
        ):
            runtime.preflight_tunnel(self.state)

    def test_launchd_path_and_no_secrets(self):
        output = Path(self.temp.name).resolve() / "render & path"
        with patch.object(runtime, "load", return_value={"identity": "a" * 32}):
            runtime.render(self.state, output)
        for path in output.glob("*.plist"):
            value = plistlib.loads(path.read_bytes())
            self.assertIn("/opt/homebrew/bin", value["EnvironmentVariables"]["PATH"])
            self.assertIn("/usr/bin", value["EnvironmentVariables"]["PATH"])
            self.assertFalse(value["RunAtLoad"])
            self.assertNotIn("TOKEN", path.read_text())

    def test_unknown_exception_class_without_message(self):
        output = io.StringIO()
        with (
            patch.object(
                sys, "argv", ["local_runtime.py", "status", "--state-dir", str(self.state)]
            ),
            patch.object(runtime, "load", side_effect=RuntimeError("synthetic-secret")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(runtime.main(), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["error_type"], "RuntimeError")
        self.assertNotIn("synthetic-secret", output.getvalue())

    def test_client_create_uses_origin_and_bounded_shared_reader(self):
        config = {"origin": "grok", "worker": "dot", "room": "a" * 24}
        runtime.env_save(
            self.state / "grok.env",
            {"ROUNDTABLE_URL": "http://127.0.0.1:12345", "ROUNDTABLE_TOKEN": "synthetic"},
        )
        args = argparse.Namespace(operation="create", task_id=None, body=None)
        with (
            patch("local_client.read_json_stdin", return_value={"title": "synthetic"}) as reader,
            patch("local_client.LocalClient") as client,
        ):
            runtime.run_client(self.state, config, args)
            reader.assert_called_once_with()
            self.assertEqual(client.call_args.args[2], "grok")
            client.return_value.call.assert_called_once_with("create", {"title": "synthetic"})
        args.task_id = "b" * 24
        with self.assertRaisesRegex(runtime.Failure, "argument_conflict"):
            runtime.run_client(self.state, config, args)


class LegacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = runtime.private_dir(Path(self.temp.name).resolve() / "old")
        self.target = runtime.private_dir(Path(self.temp.name).resolve() / "new")
        self.args = argparse.Namespace(
            origin="grok", worker="dot", server_port=12345, mcp_port=12346, proxy=None
        )
        runtime.write_json(self.source / "admin.json", {"token": "a" * 48})
        runtime.write_json(self.source / "room.json", {"id": "a" * 24, "token": "b" * 48})
        for agent in ("grok", "dot"):
            runtime.save(
                self.source / (agent + ".env"),
                f"export ROUNDTABLE_AGENT={agent}\nexport ROUNDTABLE_ROOM={'a' * 24}\nexport ROUNDTABLE_TOKEN={agent * 16}\n",
            )
        runtime.save(
            self.source / "runtime-key.env", "export CONTROL_PLANE_API_KEY=sk-synthetic-test-only\n"
        )
        runtime.write_json(
            self.source / "grok-routine.json",
            {"url": "https://routine.example.com/hook", "key": "synthetic"},
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_import_readonly_private_pending_and_no_overwrite(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        result = import_legacy(str(self.source), self.target, self.args, runtime)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        self.assertEqual(result["imported_members"], 2)
        self.assertTrue(result["routine_pending_approval"])
        self.assertFalse((self.target / "routine.json").exists())
        runtime.load(self.target)
        for p in self.target.iterdir():
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("synthetic", json.dumps(result))
        with self.assertRaisesRegex(runtime.Failure, "target_not_empty"):
            import_legacy(str(self.source), self.target, self.args, runtime)

    def test_mismatch_leaves_target_empty(self):
        runtime.save(
            self.source / "dot.env",
            f"ROUNDTABLE_AGENT=dot\nROUNDTABLE_ROOM={'c' * 24}\nROUNDTABLE_TOKEN={'d' * 48}\n",
            True,
        )
        with self.assertRaisesRegex(runtime.Failure, "scope_mismatch"):
            import_legacy(str(self.source), self.target, self.args, runtime)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_database_snapshot_receipts_suppressed_with_leftover_wal(self):
        from roundtable import Store, digest
        from terminal_receipts import TerminalReceipts

        runtime.save(self.source / "roundtable.db", "")
        store = Store(str(self.source / "roundtable.db"))
        with store.db:
            store.db.execute(
                "INSERT INTO rooms(id,token,name) VALUES(?,?,?)",
                ("a" * 24, digest("b" * 48), "Synthetic"),
            )
            for agent in ("grok", "dot"):
                store.register_bot(agent, agent, "mailbox")
                store.db.execute(
                    "INSERT INTO agents(room,id,kind,token) VALUES(?,?,?,?)",
                    ("a" * 24, agent, "mailbox", digest(agent * 16)),
                )
        task = store.handoffs.create(
            "a" * 24,
            "user",
            {
                "title": "Imported task",
                "context": "Synthetic",
                "assignments": [{"worker": "dot", "instruction": "Read only"}],
                "budget": 1,
                "request_id": "imported",
            },
        )
        store.db.close()
        runtime.save(Path(str(self.source / "roundtable.db") + "-wal"), "")
        result = import_legacy(str(self.source), self.target, self.args, runtime)
        self.assertTrue(result["history_imported"])
        adapter = Mock()
        ledger = TerminalReceipts(self.target / "terminal.db")
        try:
            outcome = ledger.send("a" * 24, {"id": task["task_id"], "status": "completed"}, adapter)
            self.assertEqual(outcome["reason"], "already_reserved")
            adapter.dispatch_terminal.assert_not_called()
        finally:
            ledger.close()

    def test_env_no_execution_or_duplicate(self):
        self.assertEqual(parse_env('export KEY="synthetic value"\n'), {"KEY": "synthetic value"})
        for text in ("KEY=$(anything)", "KEY=`anything`", "KEY=x\nKEY=y"):
            with self.assertRaises(runtime.Failure):
                parse_env(text)


if __name__ == "__main__":
    unittest.main()
