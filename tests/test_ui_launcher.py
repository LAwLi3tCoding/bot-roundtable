import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

from ui_launcher import create_launcher


class LauncherTests(unittest.TestCase):
    def test_bundle_exec_preserves_literal_paths_and_never_reads_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state space ' $(touch injected)"
            runtime = root / "fake runtime.py"
            capture = root / "capture.json"
            runtime.write_text(
                "import json,sys\nfrom pathlib import Path\nPath("
                + repr(str(capture))
                + ").write_text(json.dumps(sys.argv[1:]))\nprint('synthetic-secret')\n"
            )
            target = root / "Roundtable UI.app"
            result = create_launcher(target, state, "synthetic", sys.executable, runtime)
            self.assertFalse(result["installed"])
            self.assertFalse(state.exists())
            plist = plistlib.loads((target / "Contents/Info.plist").read_bytes())
            launcher = target / "Contents/MacOS" / plist["CFBundleExecutable"]
            run = subprocess.run([str(launcher)], capture_output=True, check=True)
            self.assertEqual(run.stdout, b"")
            self.assertEqual(run.stderr, b"")
            self.assertEqual(
                json.loads(capture.read_text()),
                ["ui", "--state-dir", str(state), "--name", "synthetic"],
            )
            self.assertNotIn("synthetic-secret", launcher.read_text())
            self.assertFalse((root / "injected").exists())
            with self.assertRaises(FileExistsError):
                create_launcher(target, state, "synthetic", sys.executable, runtime)

    def test_requires_bundle_extension(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                create_launcher(
                    Path(temporary) / "plain", "unused", "synthetic", sys.executable, "unused"
                )
