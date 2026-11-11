import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

from unittest.mock import patch

import ui_launcher
from ui_launcher import build_icns, create_launcher


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
                ["ui", "--state-dir", str(state), "--name", "synthetic", "--autostart"],
            )
            self.assertNotIn("synthetic-secret", launcher.read_text())
            self.assertFalse((root / "injected").exists())
            with self.assertRaises(FileExistsError):
                create_launcher(target, state, "synthetic", sys.executable, runtime)

    def test_logs_result_privately_and_keeps_generation_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / "state dir" / "logs"
            runtime = root / "fake runtime.py"
            runtime.write_text(
                "import json,os\nprint(json.dumps({'ok': False, 'reason': 'synthetic_reason',"
                " 'path': os.environ['PATH']}))\n"
            )
            target = root / "Roundtable UI.app"
            search = "/synthetic/bin:/usr/bin:/bin"
            create_launcher(
                target, root / "state dir", "synthetic", sys.executable, runtime, logs, search
            )
            launcher = target / "Contents/MacOS/launcher"
            run = subprocess.run([str(launcher)], capture_output=True, check=True, env={})
            self.assertEqual(run.stdout + run.stderr, b"")
            log = logs / "ui-launcher.log"
            lines = log.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            record = json.loads(lines[1])
            self.assertEqual(record["reason"], "synthetic_reason")
            self.assertEqual(record["path"], search)
            self.assertEqual(log.stat().st_mode & 0o077, 0)
            self.assertEqual(logs.stat().st_mode & 0o077, 0)

    def test_requires_bundle_extension(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                create_launcher(
                    Path(temporary) / "plain", "unused", "synthetic", sys.executable, "unused"
                )


class LauncherIconTests(unittest.TestCase):
    def test_icon_source_is_a_plain_svg(self):
        text = ui_launcher.ICON_SVG.read_text()
        self.assertTrue(text.startswith("<svg"))
        self.assertNotIn("<image", text)
        self.assertNotIn("href", text)

    def test_non_macos_skips_icon(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = Path(temporary) / "Resources"
            with (
                patch.object(ui_launcher.sys, "platform", "linux"),
                patch.object(ui_launcher.subprocess, "run") as run,
            ):
                self.assertIsNone(build_icns(ui_launcher.ICON_SVG, resources))
            run.assert_not_called()
            self.assertFalse(resources.exists())

    def test_macos_builds_iconset_and_sets_bundle_icon(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv[0])
            if argv[0] == "qlmanage":
                (Path(argv[argv.index("-o") + 1]) / "roundtable-icon.svg.png").write_bytes(b"png")
            elif argv[0] == "sips":
                Path(argv[-1]).write_bytes(b"png")
            elif argv[0] == "iconutil":
                self.assertEqual(len(list(Path(argv[3]).glob("icon_*.png"))), 10)
                Path(argv[-1]).write_bytes(b"icns")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch.object(ui_launcher.sys, "platform", "darwin"),
                patch.object(ui_launcher.shutil, "which", return_value="/usr/bin/tool"),
                patch.object(ui_launcher.subprocess, "run", side_effect=fake_run),
            ):
                create_launcher(root / "R.app", root / "state", "synthetic", sys.executable, "x")
            plist = plistlib.loads((root / "R.app/Contents/Info.plist").read_bytes())
            self.assertEqual(plist["CFBundleIconFile"], "AppIcon.icns")
            self.assertTrue((root / "R.app/Contents/Resources/AppIcon.icns").exists())
            self.assertEqual(calls[0], "qlmanage")
            self.assertEqual(calls[-1], "iconutil")

    def test_failed_icon_step_keeps_default_icon(self):
        failure = subprocess.CalledProcessError(1, "qlmanage")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch.object(ui_launcher.sys, "platform", "darwin"),
                patch.object(ui_launcher.shutil, "which", return_value="/usr/bin/tool"),
                patch.object(ui_launcher.subprocess, "run", side_effect=failure),
            ):
                create_launcher(root / "R.app", root / "state", "synthetic", sys.executable, "x")
            plist = plistlib.loads((root / "R.app/Contents/Info.plist").read_bytes())
            self.assertNotIn("CFBundleIconFile", plist)
            self.assertTrue((root / "R.app/Contents/MacOS/launcher").exists())
