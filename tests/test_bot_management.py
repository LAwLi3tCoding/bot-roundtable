"""Local cookie-only bot management, using synthetic identities and credentials."""

import http.client
import json
import secrets
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from roundtable import Problem, Store
from server import make_server


class BotManagement(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.store.register_bot("atlas", "Atlas", "mailbox")
        self.store.register_bot("nova", "Nova", "mailbox")
        self.room = self.store.create_group("Synthetic table", ["atlas", "nova"])
        self.admin = secrets.token_urlsafe(32)
        self.server = make_server(self.store, self.admin, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.base = f"/api/rooms/{self.room['id']}/bot-management"
        self.cookie = self.login(True)[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.db.close()

    def call(self, path, body=None, token=None, cookie=None, headers=None):
        values = {"Origin": self.origin, "Content-Type": "application/json"}
        if token is not None:
            values["Authorization"] = "Bearer " + token
        if cookie is not None:
            values["Cookie"] = cookie
        values.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            conn.request(
                "GET" if body is None else "POST",
                path,
                None if body is None else json.dumps(body),
                values,
            )
            response = conn.getresponse()
            return response.status, json.loads(response.read()), response.getheader("Set-Cookie")
        finally:
            conn.close()

    def login(self, cookie):
        code = self.call("/api/ui-login/issue", {}, self.admin)[1]["code"]
        status, result, header = self.call(
            "/api/ui-login/exchange", {"code": code, "cookie": cookie}
        )
        self.assertEqual(status, 200)
        return result, header.split(";", 1)[0] if header else None

    def test_cookie_origin_boundary_and_no_bearer_upgrade(self):
        bearer = self.login(False)[0]["session_token"]
        for token in (
            self.admin,
            self.room["token"],
            self.room["agent_tokens"][0]["token"],
            bearer,
        ):
            self.assertEqual(self.call(self.base, token=token)[0], 403)
            self.assertEqual(self.call(self.base, {}, token=token)[0], 403)
        self.assertEqual(self.call(self.base, cookie="roundtable_ui=" + bearer)[0], 403)
        for headers in (
            {"Origin": "https://example.invalid"},
            {"Forwarded": "for=192.0.2.1"},
            {"X-Forwarded-For": "192.0.2.1"},
            {"Host": f"localhost:{self.server.server_port}"},
        ):
            self.assertEqual(self.call(self.base, {}, cookie=self.cookie, headers=headers)[0], 403)
        state = self.call(f"/api/rooms/{self.room['id']}", cookie=self.cookie)[1]
        self.assertTrue(state["can_manage_bots"])
        self.assertFalse(
            self.call(f"/api/rooms/{self.room['id']}", token=self.admin)[1]["can_manage_bots"]
        )

    def test_revocation_observed_after_cookie_check_denies_management(self):
        sessions = self.server.ui_sessions
        # Cookie provenance succeeds, the initial validity check succeeds, then
        # revocation is observed at the dispatch authorization check.
        with patch.object(sessions, "valid", side_effect=[True, True, False]):
            self.assertEqual(self.call(self.base, {}, cookie=self.cookie)[0], 403)

    def test_create_once_edit_disable_restore_delete_retains_history(self):
        status, created, _ = self.call(
            self.base,
            {
                "id": "sage",
                "name": "Sage",
                "kind": "grok",
                "avatar": "sage",
                "wake": "grok-routine",
                "allowance_limit": 12,
            },
            cookie=self.cookie,
        )
        self.assertEqual(status, 201)
        secret = created["token"]
        self.assertNotIn(secret, str(list(self.store.db.iterdump())))
        self.store.authorize(self.room["id"], secret, "sage")
        topic = self.store.mailboxes.roundtable(self.room["id"])["id"]
        self.assertIn("bot:sage", self.store.mailboxes.roundtable(self.room["id"])["members"])
        self.store.mailboxes.post(
            self.room["id"],
            "bot:sage",
            topic,
            {"body": "Synthetic historical reply", "mentions": [], "request_id": "history"},
        )
        status, edited, _ = self.call(
            self.base + "/sage/update",
            {"name": "Sage updated", "avatar": "blue", "wake": "poll", "allowance_limit": 8},
            cookie=self.cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(edited["bot"]["allowance_limit"], 8)
        self.assertTrue(edited["setup_required"])
        self.assertEqual(self.call(self.base + "/sage/disable", {}, cookie=self.cookie)[0], 200)
        for operation in (
            lambda: self.store.authorize(self.room["id"], secret, "sage"),
            lambda: self.store.mailboxes.wake_inbox(self.room["id"], "bot:sage"),
            lambda: self.store.mailboxes.post(
                self.room["id"],
                "bot:sage",
                topic,
                {"body": "no", "mentions": [], "request_id": "disabled"},
            ),
            lambda: self.store.handoffs.inbox(self.room["id"], "bot:sage"),
            lambda: self.store.mailboxes.post(
                self.room["id"],
                "user",
                topic,
                {"body": "@sage", "mentions": ["bot:sage"], "request_id": "wake-disabled"},
            ),
        ):
            with self.assertRaises(Problem) as caught:
                operation()
            self.assertEqual(caught.exception.status, 403)
        self.assertEqual(self.call(self.base + "/sage/restore", {}, cookie=self.cookie)[0], 200)
        self.store.authorize(self.room["id"], secret, "sage")
        self.assertEqual(
            self.call(self.base + "/sage/delete", {"confirm": "wrong"}, cookie=self.cookie)[0], 400
        )
        self.assertEqual(
            self.call(self.base + "/sage/delete", {"confirm": "Sage updated"}, cookie=self.cookie)[
                0
            ],
            200,
        )
        with self.assertRaises(Problem):
            self.store.authorize(self.room["id"], secret, "sage")
        self.assertEqual(self.call(self.base + "/sage/restore", {}, cookie=self.cookie)[0], 404)
        history = self.store.mailboxes.messages(self.room["id"], "user", topic)
        self.assertEqual(history["messages"][0]["body"], "Synthetic historical reply")
        for path, token, cookie in [
            (self.base, None, self.cookie),
            ("/api/bots", self.admin, None),
            (f"/api/rooms/{self.room['id']}", self.admin, None),
        ]:
            status, response, _ = self.call(path, token=token, cookie=cookie)
            self.assertEqual(status, 200)
            self.assertNotIn(secret, json.dumps(response))
        tombstone = next(b for b in self.store.registry() if b["id"] == "sage")
        self.assertEqual(tombstone["deleted"], 1)
        self.assertEqual(tombstone["name"], "Sage updated")

    def test_creation_is_atomic_and_edits_cannot_mutate_credentials(self):
        status, _, _ = self.call(
            self.base, {"id": "sage", "name": "Sage", "allowance_limit": 21}, cookie=self.cookie
        )
        self.assertEqual(status, 400)
        self.assertFalse(any(b["id"] == "sage" for b in self.store.registry()))
        status, _, _ = self.call(
            self.base + "/atlas/update", {"token": "forbidden", "wake": "poll"}, cookie=self.cookie
        )
        self.assertEqual(status, 400)

    def test_name_only_edit_preserves_unconfigured_legacy_wake(self):
        self.assertEqual(self.store.registry()[0]["wake"], "")
        status, response, _ = self.call(
            self.base + "/atlas/update", {"name": "Atlas renamed"}, cookie=self.cookie
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["bot"]["name"], "Atlas renamed")
        self.assertEqual(response["bot"]["wake"], "")
        self.assertFalse(response["setup_required"])
        self.assertEqual(
            self.call(self.base + "/atlas/update", {"wake": ""}, cookie=self.cookie)[0], 400
        )

    def test_disabled_worker_cannot_be_assigned_or_claim(self):
        tid = self.store.handoffs.create(
            self.room["id"],
            "user",
            {
                "title": "Synthetic work",
                "context": "Context",
                "assignments": [{"worker": "nova", "instruction": "Review"}],
                "budget": 2,
                "request_id": "before-disable",
            },
        )["task_id"]
        assignment = self.store.handoffs.snapshot(self.room["id"], "user", tid)["assignments"][0]
        self.store.manage_bot(self.room["id"], "disable", {}, "nova")
        with self.assertRaises(Problem):
            self.store.handoffs.operate(
                self.room["id"],
                "bot:nova",
                "claim",
                {
                    "task_id": tid,
                    "assignment_id": assignment["id"],
                    "expected_attempt": 0,
                    "request_id": "claim-disabled",
                },
            )
        with self.assertRaises(Problem):
            self.store.handoffs.create(
                self.room["id"],
                "user",
                {
                    "title": "More work",
                    "context": "Context",
                    "assignments": [{"worker": "nova", "instruction": "Review"}],
                    "budget": 2,
                    "request_id": "after-disable",
                },
            )
        self.store.manage_bot(self.room["id"], "delete", {"confirm": "Nova"}, "nova")
        self.assertEqual(
            self.store.handoffs.snapshot(self.room["id"], "user", tid)["assignments"][0]["status"],
            "revoked",
        )


class BotMigration(unittest.TestCase):
    def test_disabled_demo_worker_is_not_executed_by_ticks(self):
        store = Store(demo=True)
        try:
            room = store.room("Synthetic demo")
            task = store.handoffs.create(
                room["id"],
                "user",
                {
                    "title": "Check",
                    "context": "Synthetic",
                    "assignments": [{"worker": "demo-planner", "instruction": "Review"}],
                    "budget": 2,
                    "request_id": "disabled-demo",
                },
            )
            store.manage_bot(room["id"], "disable", {}, "demo-planner")
            store.demo_tick()
            snapshot = store.handoffs.snapshot(room["id"], "user", task["task_id"])
            self.assertEqual(snapshot["assignments"][0]["status"], "queued")
        finally:
            store.db.close()

    def test_disable_between_demo_selection_and_inbox_does_not_stop_ticks(self):
        for tasks in (False, True):
            with self.subTest(tasks=tasks):
                store = Store(demo=True)
                try:
                    room = store.room("Synthetic demo")
                    receiver = store.handoffs if tasks else store
                    original = receiver.inbox
                    disabled = []

                    def inbox(rid, actor):
                        if actor.removeprefix("bot:") == "demo-planner" and not disabled:
                            store.manage_bot(room["id"], "disable", {}, "demo-planner")
                            disabled.append(True)
                        return original(rid, actor)

                    with patch.object(receiver, "inbox", side_effect=inbox):
                        store.demo_tick()
                    self.assertEqual(disabled, [True])
                    store.demo_tick()
                finally:
                    store.db.close()

    def test_old_registry_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.db"
            db = sqlite3.connect(path)
            db.execute(
                "CREATE TABLE bots(id TEXT PRIMARY KEY,name TEXT,kind TEXT,description TEXT)"
            )
            db.execute("INSERT INTO bots VALUES('atlas','Atlas','mailbox','')")
            db.commit()
            db.close()
            store = Store(str(path))
            try:
                bot = store.registry()[0]
                self.assertEqual(bot["avatar"], "slate")
                self.assertEqual(bot["disabled"], 0)
                self.assertEqual(bot["deleted"], 0)
            finally:
                store.db.close()
