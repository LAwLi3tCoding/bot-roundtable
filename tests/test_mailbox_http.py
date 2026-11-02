"""Mailbox authorization at the real loopback HTTP boundary, using synthetic data."""

import http.client
import json
import threading
import unittest

from roundtable import Store
from server import make_server


class MailboxHTTPTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.room = self.store.room("Synthetic scope")["id"]
        self.tokens = {
            name: self.store.add_agent(self.room, name)["token"]
            for name in ("alpha", "bravo", "charlie")
        }
        for name in self.tokens:
            self.store.grant(self.room, name, 20)
        self.server = make_server(self.store, "synthetic-admin", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.db.close()

    def call(self, suffix="", body=None, actor=None, token=None):
        path = "/api/rooms/" + self.room
        if actor:
            path += "/agents/" + actor + "/peer"
        path += "/topics" + suffix
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            connection.request(
                "GET" if body is None else "POST",
                path,
                None if body is None else json.dumps(body),
                {
                    "Authorization": "Bearer "
                    + (token or self.tokens.get(actor, "synthetic-admin")),
                    "Content-Type": "application/json",
                    "Origin": f"http://127.0.0.1:{self.server.server_port}",
                },
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_identity_cannot_be_replaced_by_owner_route_or_other_bot(self):
        self.assertEqual(self.call(token=self.tokens["alpha"])[0], 403)
        self.assertEqual(self.call(actor="bravo", token=self.tokens["alpha"])[0], 403)

    def test_ui_grants_topics_without_credential_administration(self):
        sessions = self.server.ui_sessions
        token = sessions.exchange(sessions.issue()["code"])["session_token"]
        self.assertEqual(self.call(token=token)[0], 200)
        self.assertFalse(sessions.permitted("POST", f"/api/rooms/{self.room}/join"))
        self.assertFalse(
            sessions.permitted("GET", f"/api/rooms/{self.room}/agents/alpha/peer/topics")
        )

    def test_private_delivery_owner_join_and_nonmember_denial(self):
        status, topic = self.call(
            body={"members": ["bot:bravo"], "title": "Private", "request_id": "create"},
            actor="alpha",
        )
        self.assertEqual(status, 201)
        payload = {"topic_id": topic["id"], "body": "Private message", "request_id": "send"}
        status, message = self.call("/messages", payload, "alpha")
        self.assertEqual(status, 201)
        self.assertEqual(message["sender"], "bot:alpha")
        self.assertEqual(message["recipients"], ["bot:bravo"])
        self.assertEqual(self.call(actor="charlie")[1], [])
        self.assertEqual(self.call("/query", {"topic_id": topic["id"]}, "charlie")[0], 404)
        self.assertEqual(self.call("/inbox", {}, "alpha")[1]["messages"], [])
        self.assertEqual(len(self.call("/inbox", {}, "bravo")[1]["messages"]), 1)
        self.assertEqual(self.call("/messages", payload | {"sender": "user"}, "alpha")[0], 400)
        self.assertEqual(self.call("/messages", payload | {"request_id": "owner"})[0], 403)
        status, joined = self.call("/messages", payload | {"request_id": "owner", "join": True})
        self.assertEqual(status, 201)
        self.assertEqual(joined["sender"], "user")
        self.assertEqual(joined["recipients"], ["bot:alpha", "bot:bravo"])
        self.assertEqual(self.call("/messages", payload, "alpha")[1], message)
