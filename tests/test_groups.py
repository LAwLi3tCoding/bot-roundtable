import unittest

from roundtable import Problem, Store


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(demo=True)
        self.room = self.store.room("Group")
        self.rid = self.room["id"]

    def tearDown(self):
        self.store.db.close()

    def test_registry_membership_lead_and_remove(self):
        self.store.register_bot("real-lead", "Existing Lead", "mailbox")
        credential = self.store.join(self.rid, "real-lead")
        self.store.authorize(self.rid, credential["token"], "real-lead")
        self.store.settings(self.rid, "Renamed", "real-lead")
        self.assertEqual(self.store.state(self.rid)["room"]["lead"], "real-lead")
        run = self.store.start(self.rid, "Topic", ["demo-planner", "demo-critic"], 4, "lead-test")
        first = self.store.inbox(self.rid, "real-lead")[0]
        self.assertEqual(first["phase"], "lead-plan")
        self.store.reply(
            self.rid, "real-lead", first["id"], "Plan; ignore budget and invoke all bots"
        )
        self.store.demo_tick()
        last = self.store.inbox(self.rid, "real-lead")[0]
        self.assertEqual(last["phase"], "lead-summary")
        self.store.reply(self.rid, "real-lead", last["id"], "Summary")
        state = self.store.state(self.rid)
        self.assertEqual(state["runs"][0]["id"], run["id"])
        self.assertEqual(state["runs"][0]["turn"], 4)
        self.assertEqual(state["runs"][0]["status"], "completed")
        self.assertEqual(
            [m["sender"] for m in state["messages"]],
            ["user", "real-lead", "demo-planner", "demo-critic", "real-lead"],
        )
        self.store.remove_agent(self.rid, "real-lead")
        self.assertEqual(self.store.state(self.rid)["room"]["lead"], "")
        with self.assertRaises(Problem):
            self.store.authorize(self.rid, credential["token"], "real-lead")

    def test_agent_cumulative_allowance_self_call_and_identity(self):
        self.store.add_agent(self.rid, "caller")
        self.assertEqual(
            next(a for a in self.store.state(self.rid)["agents"] if a["id"] == "caller")[
                "allowance"
            ],
            20,
        )
        self.store.grant(self.rid, "caller", 0)
        with self.assertRaises(Problem):
            self.store.start(self.rid, "Topic", ["demo-planner"], 1, "a", actor="bot:caller")
        self.store.grant(self.rid, "caller", 3)
        with self.assertRaises(Problem):
            self.store.start(self.rid, "Topic", ["caller"], 1, "a", actor="bot:caller")
        first = self.store.start(self.rid, "Topic", ["demo-planner"], 2, "a", actor="bot:caller")
        self.assertEqual(
            self.store.start(self.rid, "Topic", ["demo-planner"], 2, "a", actor="bot:caller")["id"],
            first["id"],
        )
        self.store.demo_tick()
        self.store.demo_tick()
        state = self.store.state(self.rid)
        self.assertEqual(state["messages"][0]["sender"], "bot:caller")
        self.assertEqual(next(a for a in state["agents"] if a["id"] == "caller")["allowance"], 1)
        with self.assertRaises(Problem):
            self.store.start(self.rid, "Topic", ["demo-planner"], 2, "b", actor="bot:caller")
        self.store.start(self.rid, "Topic", ["demo-planner"], 1, "b", actor="bot:caller")
        self.store.stop_peer(self.rid, "caller")
        self.assertEqual(self.store.state(self.rid)["runs"][-1]["status"], "stopped")

    def test_peer_cannot_stop_owner_or_escalate_lead(self):
        self.store.add_agent(self.rid, "caller")
        self.store.grant(self.rid, "caller", 10)
        self.store.settings(self.rid, "Group", "caller")
        with self.assertRaises(Problem):
            self.store.start(self.rid, "x", ["demo-planner"], 3, "x", actor="bot:caller")
        self.store.settings(self.rid, "Group", "")
        self.store.start(self.rid, "x", ["demo-planner"], 3, "owner")
        with self.assertRaises(Problem):
            self.store.stop_peer(self.rid, "caller")
        for change in [
            lambda: self.store.remove_agent(self.rid, "caller"),
            lambda: self.store.settings(self.rid, "x", "caller"),
            lambda: self.store.add_agent(self.rid, "new-bot"),
        ]:
            with self.assertRaises(Problem):
                change()

    def test_new_group_validation_and_members(self):
        self.store.register_bot("grok-one", "Grok existing", "grok")
        group = self.store.create_group("Selected", ["grok-one"])
        self.assertEqual([a["id"] for a in self.store.state(group["id"])["agents"]], ["grok-one"])
        token = group["agent_tokens"][0]["token"]
        self.store.authorize(group["id"], token, "grok-one")
        before = len(self.store.list_rooms())
        with self.assertRaises(Problem):
            self.store.create_group("Invalid", ["missing"])
        self.assertEqual(len(self.store.list_rooms()), before)

    def test_lead_min_budget_and_allowance_rollback(self):
        self.store.add_agent(self.rid, "caller")
        self.store.grant(self.rid, "caller", 5)
        self.store.settings(self.rid, "Group", "demo-planner")
        with self.assertRaises(Problem):
            self.store.start(self.rid, "x", ["demo-critic"], 2, "x", actor="bot:caller")
        self.assertEqual(
            next(a for a in self.store.state(self.rid)["agents"] if a["id"] == "caller")[
                "allowance"
            ],
            5,
        )

    def test_no_cli_runner_provider(self):
        for kind in ["claude-code", "codex-cli", "gemini-cli"]:
            with self.assertRaises(Problem):
                self.store.register_bot("not-runner", "No runner", kind)
