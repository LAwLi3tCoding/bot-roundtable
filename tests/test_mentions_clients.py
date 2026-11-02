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
        message = store.discussions.post(
            room["id"],
            "user",
            {"body": "Question", "mentions": ["reader-bot"], "request_id": "question"},
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
                    inbox = unpack(await session.call_tool("receive_mentions", {"after": 0}))
                    self.assertEqual(inbox["messages"][0]["id"], message["id"])
                    payload = {
                        "body": "Answer",
                        "mentions": [],
                        "request_id": "answer",
                        "reply_to": message["id"],
                    }
                    reply = unpack(await session.call_tool("post_discussion_message", payload))
                    self.assertEqual(reply["reply_to"], message["id"])
                    self.assertEqual(client.call("message", payload)["id"], reply["id"])
                    self.assertEqual(
                        client.call("mentions", {"after": inbox["next_cursor"]})["messages"], []
                    )
                    store.remove_agent(room["id"], bot["id"])
                    with self.assertRaises(ValueError):
                        client.call("mentions", {"after": 0})
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
                result = json.loads(response.read())
                self.assertLess(response.status, 300)
                return result
            finally:
                conn.close()

        try:
            human = post(
                f"/api/rooms/{room['id']}/messages",
                room["token"],
                {
                    "body": "human",
                    "request_id": "human",
                    "mentions": [],
                    "actor": "bot:alpha",
                    "source": "bot",
                    "sender": "alpha",
                },
            )
            self.assertEqual(human["sender"], "user")
            for bot in ("alpha", "bravo"):
                self.assertEqual(
                    len(store.discussions.inbox(room["id"], "bot:" + bot, {})["messages"]), 1
                )
            for forged in ("user", "system"):
                reply = post(
                    f"/api/rooms/{room['id']}/agents/alpha/peer/messages",
                    alpha["token"],
                    {
                        "body": "bot",
                        "request_id": forged,
                        "mentions": [],
                        "reply_to": human["id"],
                        "actor": forged,
                        "source": forged,
                        "sender": forged,
                    },
                )
                self.assertEqual(reply["sender"], "bot:alpha")
                for bot in ("alpha", "bravo"):
                    self.assertEqual(
                        store.discussions.inbox(room["id"], "bot:" + bot, {"after": human["id"]})[
                            "messages"
                        ],
                        [],
                    )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.db.close()
