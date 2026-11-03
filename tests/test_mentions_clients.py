"""Synthetic SDK and CLI protocol coverage; no provider accounts."""

import http.client
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from local_client import LocalClient
from roundtable import Store
from server import make_server


class MentionClients(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_read_reply_cursor_and_cli_replay(self):
        store = Store()
        room = store.room("Synthetic mentions")
        bot = store.add_agent(room["id"], "reader-bot")
        topic = store.mailboxes.create(
            room["id"], "user", {"members": ["bot:reader-bot"], "title": "Q", "request_id": "t"}
        )
        message = store.mailboxes.post(
            room["id"], "user", topic["id"], {"body": "Question", "request_id": "question"}
        )
        server = make_server(store, secrets.token_urlsafe(32), port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        client = LocalClient(base, room["id"], bot["id"], bot["token"])
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).resolve().parents[1] / "mcp_bridge.py")],
            env={
                **os.environ,
                "ROUNDTABLE_URL": base,
                "ROUNDTABLE_ROOM": room["id"],
                "ROUNDTABLE_AGENT": bot["id"],
                "ROUNDTABLE_TOKEN": bot["token"],
            },
        )

        def unpack(result):
            self.assertFalse(result.isError, result.content)
            content = result.structuredContent
            return (
                content.get("result", content)
                if content is not None
                else json.loads(result.content[0].text)
            )

        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    inbox = unpack(await session.call_tool("receive_messages", {"after": 0}))
                    self.assertEqual(inbox["messages"][0]["id"], message["id"])
                    payload = {
                        "body": "Answer",
                        "mentions": [],
                        "request_id": "answer",
                        "topic_id": topic["id"],
                    }
                    reply = unpack(await session.call_tool("reply_to_topic", payload))
                    self.assertEqual(reply["topic"], topic["id"])
                    self.assertEqual(client.call("reply", payload)["id"], reply["id"])
                    self.assertEqual(
                        client.call("mailbox", {"after": inbox["next_cursor"]})["messages"], []
                    )
                    store.remove_agent(room["id"], bot["id"])
                    with self.assertRaises(ValueError):
                        client.call("mailbox", {"after": 0})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.db.close()


class HttpIdentityBoundary(unittest.TestCase):
    def test_authenticated_identity_overrides_payload(self):
        store = Store()
        room = store.room("Synthetic identity")
        alpha = store.add_agent(room["id"], "alpha")
        store.add_agent(room["id"], "bravo")
        store.grant(room["id"], "alpha", 20)
        server = make_server(store, secrets.token_urlsafe(32), port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()

        def post(path, token, payload):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
            try:
                conn.request(
                    "POST",
                    path,
                    json.dumps(payload),
                    {"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                )
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        try:
            forged = {"actor": "bot:alpha", "source": "bot", "sender": "alpha"}
            status, topic = post(
                f"/api/rooms/{room['id']}/topics",
                room["token"],
                {"members": ["bot:alpha"], "title": "Synthetic", "request_id": "topic"},
            )
            self.assertEqual(status, 201, topic)
            user_path = f"/api/rooms/{room['id']}/topics/messages"
            message = {"topic_id": topic["id"], "body": "human", "request_id": "human"}
            self.assertEqual(post(user_path, room["token"], {**message, **forged})[0], 400)
            status, human = post(user_path, room["token"], message)
            self.assertEqual((status, human["sender"]), (201, "user"))
            bot_path = f"/api/rooms/{room['id']}/agents/alpha/peer/topics/messages"
            reply = {"topic_id": topic["id"], "body": "bot", "request_id": "bot", "mentions": []}
            for value in ("user", "system"):
                spoofed = {**reply, "actor": value, "source": value, "sender": value}
                self.assertEqual(post(bot_path, alpha["token"], spoofed)[0], 400)
            status, sent = post(bot_path, alpha["token"], reply)
            self.assertEqual((status, sent["sender"]), (201, "bot:alpha"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.db.close()
