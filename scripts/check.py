"""Bounded diagnostic using inherited scoped environment; never opens secret files."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("doctor", "probe"))
    args = parser.parse_args()
    print("Starting local diagnostic (15s limit)", file=sys.stderr, flush=True)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-u",
                str(Path(__file__).resolve().parents[1] / "local_client.py"),
                args.operation,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        print(result.stdout or '{"ok":false,"reason":"child_no_output"}', end="", flush=True)
        return result.returncode
    except subprocess.TimeoutExpired:
        print(json.dumps({"ok": False, "reason": "probe_total_timeout"}))
        return 124
    except OSError:
        print(json.dumps({"ok": False, "reason": "local_wrapper_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
