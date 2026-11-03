import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install.sh"


def fake_python(directory, name, version):
    ok = 0 if version in ((3, 12), (3, 13)) else 1
    path = Path(directory) / name
    path.write_text(
        '#!/bin/sh\ncase "$2" in *version_info*) exit %d ;; esac\necho %d.%d.0\n' % (ok, *version)
    )
    path.chmod(0o755)


class InstallScript(unittest.TestCase):
    def run_check(self, versions):
        with tempfile.TemporaryDirectory() as bin_dir:
            for name, version in versions.items():
                fake_python(bin_dir, name, version)
            for tool in ("uname", "dirname", "sh"):
                os.symlink(shutil.which(tool), Path(bin_dir) / tool)
            env = {"PATH": bin_dir, "HOME": bin_dir}
            return subprocess.run(
                ["/bin/sh", str(SCRIPT), "--check"], capture_output=True, text=True, env=env
            )

    def test_rejects_unsupported_python(self):
        result = self.run_check({"python3": (3, 11)})
        self.assertEqual(result.returncode, 3)
        self.assertIn("missing: Python 3.12 or 3.13", result.stderr)

    def test_check_reports_supported_python_without_changes(self):
        result = self.run_check({"python3.12": (3, 12)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok: python 3.12.0", result.stdout)
        self.assertIn(".venv", result.stdout)

    def test_rejects_unknown_argument(self):
        result = subprocess.run(["/bin/sh", str(SCRIPT), "--bogus"], capture_output=True)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
