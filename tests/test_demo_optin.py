import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from roundtable import Problem, Store

ROOT = Path(__file__).resolve().parents[1]
DEMO = {"demo-planner", "demo-critic"}


def ids(store):
    return {bot["id"] for bot in store.registry()}


class DemoOptInTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = self.directory.name + "/roundtable.db"

    def tearDown(self):
        self.directory.cleanup()

    def test_default_store_has_no_demo_bots_or_members(self):
        store = Store(self.db)
        self.assertFalse(DEMO & ids(store))
        room = store.room("Plain")
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM agents").fetchone()[0], 0)
        self.assertEqual(store.state(room["id"])["room"]["name"], "Plain")
        with self.assertRaises(Problem):
            store.create_group("No members")
        store.db.close()
        reopened = Store(self.db)
        self.assertFalse(DEMO & ids(reopened))
        reopened.db.close()

    def test_demo_mode_seeds_registry_and_rooms(self):
        store = Store(self.db, demo=True)
        self.assertLessEqual(DEMO, ids(store))
        room = store.create_group("Demo")
        members = {
            r[0] for r in store.db.execute("SELECT id FROM agents WHERE room=?", (room["id"],))
        }
        self.assertEqual(members, DEMO)
        store.db.close()

    def test_legacy_unreferenced_demo_hidden_and_pruned_without_reseed(self):
        Store(self.db, demo=True).db.close()
        store = Store(self.db)
        self.assertFalse(DEMO & ids(store))
        self.assertEqual(
            store.prune_demo(), {"removed": ["demo-planner", "demo-critic"], "kept": []}
        )
        store.db.close()
        reopened = Store(self.db)
        count = reopened.db.execute("SELECT COUNT(*) FROM bots WHERE kind='demo'").fetchone()[0]
        self.assertEqual(count, 0)
        reopened.db.close()

    def test_referenced_demo_stays_visible_and_is_kept(self):
        legacy = Store(self.db, demo=True)
        legacy.room("Legacy room")
        legacy.db.close()
        store = Store(self.db)
        self.assertLessEqual(DEMO, ids(store))
        self.assertEqual(
            store.prune_demo(), {"removed": [], "kept": ["demo-planner", "demo-critic"]}
        )
        store.db.close()

    def run_server(self, *args, env=None):
        merged = {k: v for k, v in os.environ.items() if k != "ROUNDTABLE_DEMO"}
        merged.update(env or {})
        return subprocess.run(
            [sys.executable, str(ROOT / "server.py"), "--db", self.db, *args],
            capture_output=True,
            text=True,
            env=merged,
            timeout=30,
        )

    def test_prune_cli_is_scoped_and_has_no_startup_side_effects(self):
        legacy = Store(self.db, demo=True)
        legacy.register_bot("real-bot", "Real", "mailbox")
        legacy.db.execute("INSERT INTO runs(id,room,status) VALUES ('r1','x','running')")
        legacy.db.commit()
        legacy.db.close()
        result = self.run_server("--prune-demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["removed"], ["demo-planner", "demo-critic"])
        db = sqlite3.connect(self.db)
        self.assertEqual([r[0] for r in db.execute("SELECT id FROM bots")], ["real-bot"])
        self.assertEqual(db.execute("SELECT status FROM runs").fetchone()[0], "running")
        db.close()

    def test_prune_cli_refuses_demo_mode_and_missing_database(self):
        Store(self.db).db.close()
        self.assertNotEqual(
            self.run_server("--prune-demo", env={"ROUNDTABLE_DEMO": "1"}).returncode, 0
        )
        self.assertNotEqual(self.run_server("--prune-demo", "--demo").returncode, 0)
        missing = self.directory.name + "/missing.db"
        result = subprocess.run(
            [sys.executable, str(ROOT / "server.py"), "--db", missing, "--prune-demo"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(Path(missing).exists())


if __name__ == "__main__":
    unittest.main()
