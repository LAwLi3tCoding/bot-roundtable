"""Synthetic multi-Bot runtime configuration and authentication regressions."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import local_runtime as runtime
from terminal_receipts import configured_worker
from mcp_http import OriginGate


class MultiBotRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = runtime.private_dir(Path(self.temp.name).resolve() / "instance")
        self.config = {
            "origin": "grok",
            "worker": "dot",
            "room": "a" * 24,
            "server_port": 12345,
            "proxy": "",
        }
        for bot in ("grok", "dot"):
            runtime.env_save(
                self.state / (bot + ".env"),
                {
                    "ROUNDTABLE_URL": "http://127.0.0.1:12345",
                    "ROUNDTABLE_TOKEN": "synthetic-" + bot,
                },
            )

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_bot_defaults(self):
        bots = runtime.instance_bots(self.config)
        self.assertEqual([b["id"] for b in bots], ["grok", "dot"])
        self.assertEqual([b["wake"] for b in bots], ["grok-routine", "mcp-events"])
        self.assertNotIn("bots", self.config)

    def test_add_third_bot_and_client_selects_own_mailbox(self):
        args = argparse.Namespace(
            bot="helper",
            kind="grok",
            wake=None,
            allowance=20,
            operation="mailbox",
            task_id=None,
            body=None,
        )
        with (
            patch.object(runtime, "get_admin_token", return_value="synthetic-admin"),
            patch.object(
                runtime, "request", side_effect=[[], {}, {"token": "synthetic-helper"}, {}]
            ) as request,
        ):
            runtime.add_bot(self.state, self.config, args)
        self.assertEqual(request.call_args.args[-1], {"id": "helper", "allowance": 20})
        self.assertEqual(
            self.config["bots"][-1], {"id": "helper", "kind": "grok", "wake": "grok-routine"}
        )
        self.assertEqual((self.state / "helper.env").stat().st_mode & 0o777, 0o600)
        with (
            patch("local_client.LocalClient") as client,
            patch("local_client.read_json_stdin", return_value={}),
        ):
            runtime.run_client(self.state, self.config, args)
        self.assertEqual(client.call_args.args[2:], ("helper", "synthetic-helper"))
        client.return_value.call.assert_called_once_with("mailbox", {})
        args.bot = "unknown"
        with self.assertRaisesRegex(runtime.Failure, "unknown_bot"):
            runtime.run_client(self.state, self.config, args)

    def test_retry_reuses_registration_and_saved_credential(self):
        args = argparse.Namespace(bot="helper", kind="grok", wake=None, allowance=20)
        runtime.env_save(
            self.state / "helper.env",
            {
                "ROUNDTABLE_URL": "http://127.0.0.1:12345",
                "ROUNDTABLE_ROOM": self.config["room"],
                "ROUNDTABLE_AGENT": "helper",
                "ROUNDTABLE_TOKEN": "synthetic-helper",
            },
        )
        with (
            patch.object(runtime, "get_admin_token", return_value="synthetic-admin"),
            patch.object(
                runtime,
                "request",
                side_effect=[[{"id": "helper", "kind": "grok"}], {"authorized": True}, {}],
            ) as request,
        ):
            runtime.add_bot(self.state, self.config, args)
        self.assertEqual(len(request.call_args_list), 3)
        self.assertTrue(request.call_args_list[1].args[1].endswith("/helper/access"))

    def test_routine_files_route_to_independent_bot_workers(self):
        self.config["bots"] = runtime.instance_bots(self.config) + [
            {"id": "helper", "kind": "grok", "wake": "grok-routine"}
        ]
        for bot in ("grok", "helper"):
            with (
                patch.object(
                    runtime,
                    "hidden",
                    side_effect=["https://example.invalid/" + bot, "synthetic-routine-key"],
                ),
                patch("grok_adapter.GrokWebhook"),
            ):
                runtime.configure_secret(self.state, self.config, "set-grok-routine", False, bot)
            self.assertTrue((self.state / f"routine-{bot}.json").exists())
        with (
            patch.object(runtime, "get_admin_token", return_value="synthetic-admin"),
            patch("grok_adapter.GrokWebhook"),
        ):
            env = runtime.child_env(self.state, self.config, "server")
        configs = json.loads(env["ROUNDTABLE_BOT_ROUTINES"])
        self.assertEqual([c["bot"] for c in configs], ["grok", "helper"])
        with (
            patch.dict(os.environ, env, clear=True),
            patch("terminal_receipts.private_ledger"),
            patch("terminal_receipts.GrokWebhook") as adapter,
        ):
            workers = configured_worker("synthetic.db")
        self.assertEqual([w.origin for w in workers.workers], ["grok", "helper"])
        self.assertEqual(
            [call.args[0] for call in adapter.call_args_list],
            ["https://example.invalid/grok", "https://example.invalid/helper"],
        )

    def test_mcp_grants_include_only_event_bots(self):
        self.config["bots"] = runtime.instance_bots(self.config) + [
            {"id": "helper", "kind": "dot", "wake": "mcp-events"}
        ]
        runtime.env_save(self.state / "helper.env", {"ROUNDTABLE_TOKEN": "synthetic-helper"})
        env = runtime.child_env(self.state, self.config, "mcp")
        grants = json.loads(env["ROUNDTABLE_HTTP_GRANTS"])
        self.assertEqual([g["agent"] for g in grants], ["dot", "helper"])
        self.assertEqual(env["ROUNDTABLE_MULTI_BOT_AUTH"], "1")

    def test_added_third_bot_receives_its_wake_and_mailbox(self):
        from roundtable import Store
        from server import make_server
        from terminal_receipts import TerminalWorker
        from local_client import LocalClient

        store = Store(str(self.state / "source.db"))
        room = store.room("Synthetic multi Bot workspace")["id"]
        store.add_agent(room, "grok", "grok")
        store.add_agent(room, "dot", "dot")
        server = make_server(store, "synthetic-admin", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.config.update(room=room, server_port=server.server_port)
        worker = None
        try:
            args = argparse.Namespace(bot="helper", kind="grok", wake=None, allowance=20)
            with patch.object(runtime, "get_admin_token", return_value="synthetic-admin"):
                runtime.add_bot(self.state, self.config, args)
            adapter = Mock()
            worker = TerminalWorker(
                self.state / "source.db",
                self.state / "ledger.db",
                room,
                "helper",
                adapter,
                interval=0.01,
            )
            worker.start()
            topic = store.mailboxes.create(
                room,
                "user",
                {
                    "members": ["helper", "grok"],
                    "title": "Synthetic conversation",
                    "request_id": "new-topic",
                },
            )
            message = store.mailboxes.post(
                room,
                "user",
                topic["id"],
                {"body": "Hello helper", "mentions": ["bot:helper"], "request_id": "hello"},
            )
            deadline = time.monotonic() + 3
            while not adapter.notify.called and time.monotonic() < deadline:
                time.sleep(0.01)
            adapter.notify.assert_called_once()
            self.assertEqual(adapter.notify.call_args.args, ("message", str(message["id"])))
            credential = runtime.env_read(self.state / "helper.env")
            client = LocalClient(
                credential["ROUNDTABLE_URL"], room, "helper", credential["ROUNDTABLE_TOKEN"]
            )
            inbox = client.call("mailbox", {})
            self.assertEqual(inbox["messages"][0]["body"], "Hello helper")
        finally:
            if worker:
                worker.stop()
            server.shutdown()
            thread.join()
            server.server_close()
            store.db.close()


class MultiBotAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_grants_only_and_host_checks_preserved(self):
        called = []

        async def app(scope, receive, send):
            called.append(True)

        gate = OriginGate(app, ["localhost"], [], ["Bearer synthetic-one", "Bearer synthetic-two"])
        for token, host, accepted in [
            ("synthetic-one", "localhost", True),
            ("synthetic-two", "localhost", True),
            ("unknown", "localhost", False),
            ("synthetic-two", "example.invalid", False),
        ]:
            messages = []

            async def send(message):
                messages.append(message)

            before = len(called)
            await gate(
                {
                    "type": "http",
                    "headers": [
                        (b"host", host.encode()),
                        (b"authorization", ("Bearer " + token).encode()),
                    ],
                },
                None,
                send,
            )
            self.assertEqual(len(called) > before, accepted)
            if not accepted:
                self.assertEqual(messages[0]["status"], 403)
