import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ui_launcher import CLIENT_MARKER, install_client_command

ROOT = Path(__file__).resolve().parents[1]


def fake_runtime(root, capture):
    runtime = root / "fake runtime.py"
    runtime.write_text(
        "import json,sys\nfrom pathlib import Path\nPath("
        + repr(str(capture))
        + ").write_text(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}))\n"
    )
    return runtime


class ClientCommandTests(unittest.TestCase):
    def test_wrapper_content_and_argument_passthrough(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state space ' $(touch injected)"
            capture = root / "capture.json"
            runtime = fake_runtime(root, capture)
            target = root / "bin" / "roundtable-client"
            result = install_client_command(target, state, "synthetic", sys.executable, runtime)
            self.assertEqual(result, {"ok": True, "client": str(target)})
            self.assertFalse(state.exists())
            text = target.read_text()
            self.assertTrue(text.startswith("#!/bin/sh\n" + CLIENT_MARKER + "\nexec "))
            self.assertTrue(text.endswith(' "$@"\n'))
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            run = subprocess.run(
                [str(target), "--bot", "grok", "--operation", "reply", "--body", "a b 'c' $HOME"],
                input=b'{"after":0}',
                capture_output=True,
                check=True,
            )
            self.assertEqual(run.stderr, b"")
            seen = json.loads(capture.read_text())
            self.assertEqual(
                seen["argv"],
                [
                    "client",
                    "--state-dir",
                    str(state),
                    "--name",
                    "synthetic",
                    "--bot",
                    "grok",
                    "--operation",
                    "reply",
                    "--body",
                    "a b 'c' $HOME",
                ],
            )
            self.assertEqual(seen["stdin"], '{"after":0}')
            self.assertFalse((root / "injected").exists())

    def test_rerun_replaces_own_wrapper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "roundtable-client"
            install_client_command(target, root / "old", "default", sys.executable, root / "r.py")
            first = target.read_text()
            install_client_command(target, root / "old", "default", sys.executable, root / "r.py")
            self.assertEqual(target.read_text(), first)
            install_client_command(target, root / "new", "default", sys.executable, root / "r.py")
            self.assertIn(str(root / "new"), target.read_text())
            self.assertNotIn(str(root / "old"), target.read_text())
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["roundtable-client"])

    def test_refuses_foreign_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            foreign = root / "roundtable-client"
            foreign.write_text("#!/bin/sh\necho mine\n")
            with self.assertRaises(FileExistsError):
                install_client_command(foreign, root, "default", sys.executable, root / "r.py")
            self.assertEqual(foreign.read_text(), "#!/bin/sh\necho mine\n")
            link = root / "link"
            link.symlink_to(foreign)
            with self.assertRaises(FileExistsError):
                install_client_command(link, root, "default", sys.executable, root / "r.py")

    def test_cli_requires_configured_instance_and_writes_wrapper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            target = root / "out" / "roundtable-client"
            command = [
                sys.executable,
                str(ROOT / "scripts/local_runtime.py"),
                "install-client",
                "--state-dir",
                str(state),
                "--output",
                str(target),
            ]
            env = {k: v for k, v in os.environ.items() if not k.startswith("ROUNDTABLE_")}
            missing = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(missing.returncode, 1)
            self.assertEqual(json.loads(missing.stdout)["reason"], "not_configured_run_setup")
            self.assertFalse(target.exists())
            state.mkdir()
            (state / "instance.json").write_text("{}")
            done = subprocess.run(command, capture_output=True, text=True, env=env, check=True)
            self.assertEqual(json.loads(done.stdout), {"ok": True, "client": str(target)})
            text = target.read_text()
            self.assertIn(str(ROOT / "scripts/local_runtime.py"), text)
            self.assertIn("client --state-dir " + str(state) + " --name default", text)
