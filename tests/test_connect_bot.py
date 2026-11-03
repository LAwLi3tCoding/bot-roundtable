"""Import web-issued synthetic credentials; never create or rotate credentials."""

import argparse
import json
import secrets
import unittest
import threading

from roundtable import Store
from server import make_server
from unittest.mock import patch

import test_multi_bot_runtime as fixture

runtime = fixture.runtime


class ConnectBotTests(unittest.TestCase):
    setUp = fixture.MultiBotRuntimeTests.setUp
    tearDown = fixture.MultiBotRuntimeTests.tearDown

    def test_import_and_retry_update_wake_without_exposing_token(self):
        token = secrets.token_urlsafe(32)
        args = argparse.Namespace(bot="helper")
        registered = {"id": "helper", "kind": "grok", "wake": "grok-routine"}
        with (
            patch.object(runtime, "get_admin_token", return_value="synthetic-admin"),
            patch.object(runtime, "hidden", return_value=token) as hidden,
            patch.object(
                runtime, "request", side_effect=[[registered], {"authorized": True}]
            ) as api,
        ):
            result = runtime.connect_bot(self.state, self.config, args)
        hidden.assert_called_once()
        self.assertTrue(all(len(call.args) == 3 for call in api.call_args_list))
        self.assertNotIn(token, json.dumps(result))
        path = self.state / "helper.env"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(runtime.env_read(path)["ROUNDTABLE_TOKEN"], token)
        registered["wake"] = "poll"
        with (
            patch.object(runtime, "get_admin_token", return_value="synthetic-admin"),
            patch.object(runtime, "hidden") as hidden,
            patch.object(runtime, "request", side_effect=[[registered], {"authorized": True}]),
        ):
            runtime.connect_bot(self.state, self.config, args)
        hidden.assert_not_called()
        self.assertEqual(self.config["bots"][-1]["wake"], "poll")
        self.assertEqual(len(self.config["bots"]), 3)
        self.assertEqual(runtime.env_read(path)["ROUNDTABLE_TOKEN"], token)

    def test_rejected_credential_does_not_create_local_files(self):
        registered = {"id": "helper", "kind": "dot", "wake": "mcp-events"}
        with (
            patch.object(runtime, "get_admin_token", return_value="synthetic-admin"),
            patch.object(runtime, "hidden", return_value=secrets.token_urlsafe(32)),
            patch.object(runtime, "request", side_effect=[[registered], {"authorized": False}]),
            self.assertRaisesRegex(runtime.Failure, "invalid_bot_credential"),
        ):
            runtime.connect_bot(self.state, self.config, argparse.Namespace(bot="helper"))
        self.assertFalse((self.state / "helper.env").exists())
        self.assertNotIn("bots", self.config)

    def test_disabled_or_deleted_bot_is_not_imported(self):
        for flag in ("disabled", "deleted"):
            with (
                self.subTest(flag=flag),
                patch.object(runtime, "get_admin_token", return_value="synthetic-admin"),
                patch.object(runtime, "hidden") as hidden,
                patch.object(runtime, "request", return_value=[{"id": "helper", flag: True}]),
                self.assertRaisesRegex(runtime.Failure, "bot_unavailable"),
            ):
                runtime.connect_bot(self.state, self.config, argparse.Namespace(bot="helper"))
            hidden.assert_not_called()

    def test_web_created_bot_imports_and_reads_its_mailbox(self):
        store = Store()
        store.register_bot("atlas", "Atlas", "mailbox")
        room = store.create_group("Synthetic import test", ["atlas"])
        issued = store.manage_bot(
            room["id"],
            "create",
            {
                "id": "helper",
                "name": "Helper",
                "kind": "grok",
                "avatar": "blue",
                "wake": "grok-routine",
                "allowance_limit": 20,
            },
        )
        admin = secrets.token_urlsafe(32)
        server = make_server(store, admin, port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.config.update(server_port=server.server_port, room=room["id"])
        try:
            with (
                patch.object(runtime, "get_admin_token", return_value=admin),
                patch.object(runtime, "hidden", return_value=issued["token"]),
            ):
                runtime.connect_bot(self.state, self.config, argparse.Namespace(bot="helper"))
            topic = store.mailboxes.roundtable(room["id"])["id"]
            store.mailboxes.post(
                room["id"],
                "user",
                topic,
                {
                    "body": "Synthetic greeting",
                    "mentions": ["bot:helper"],
                    "request_id": "greeting",
                },
            )
            from local_client import LocalClient

            env = runtime.env_read(self.state / "helper.env")
            client = LocalClient(
                env["ROUNDTABLE_URL"], room["id"], "helper", env["ROUNDTABLE_TOKEN"]
            )
            self.assertEqual(
                client.call("mailbox", {})["messages"][0]["body"], "Synthetic greeting"
            )
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
            store.db.close()
