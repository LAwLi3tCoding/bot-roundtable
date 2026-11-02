"""Generate an explicitly requested macOS launcher; never read instance credentials."""

from pathlib import Path
import plistlib
import shlex
import shutil


def create_launcher(output, state, name, python, runtime):
    """Create a new bundle only; paths and runtime identity are fixed at generation."""
    target = Path(output).expanduser().absolute()
    if target.suffix != ".app":
        raise ValueError("launcher_output_requires_app_suffix")
    # mkdir must fail for existing bundles/symlinks, avoiding destructive replacement.
    target.mkdir(mode=0o700)
    try:
        executable_dir = target / "Contents" / "MacOS"
        executable_dir.mkdir(parents=True, mode=0o700)
        argv = [
            str(Path(python).absolute()),
            str(Path(runtime).absolute()),
            "ui",
            "--state-dir",
            str(Path(state).expanduser().absolute()),
            "--name",
            name,
        ]
        launcher = executable_dir / "launcher"
        launcher.write_text("#!/bin/sh\nexec " + shlex.join(argv) + " >/dev/null 2>&1\n")
        launcher.chmod(0o700)
        with (target / "Contents" / "Info.plist").open("wb") as handle:
            plistlib.dump(
                {
                    "CFBundleExecutable": "launcher",
                    "CFBundleIdentifier": "local.roundtable.ui",
                    "CFBundleName": "Bot Roundtable",
                    "CFBundlePackageType": "APPL",
                    "CFBundleVersion": "1",
                    "LSUIElement": True,
                },
                handle,
            )
    except BaseException:
        shutil.rmtree(target)
        raise
    return {"ok": True, "launcher": str(target), "installed": False}
