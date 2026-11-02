"""Checkpoint closed managed SQLite databases after confirmed instance shutdown."""

from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import subprocess

from admin_credentials import check_private
from runtime_errors import RuntimeFailure


def require_closed(paths):
    binary = shutil.which("lsof")
    if not binary:
        raise RuntimeFailure("database_inspection_unavailable_install_lsof")
    result = subprocess.run(
        [binary, "-t", "--", *[str(p) for p in paths]], capture_output=True, timeout=10
    )
    if result.returncode == 0 and result.stdout.strip():
        raise RuntimeFailure("database_in_use_stop_instance")
    if result.returncode not in (0, 1):
        raise RuntimeFailure("database_process_inspection_failed")


def checkpoint_state(state):
    paths = [p for p in Path(state).glob("*.db") if p.is_file()]
    if paths:
        require_closed(paths)
    for path in paths:
        check_private(path)
        with closing(sqlite3.connect(path, timeout=1)) as db:
            if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                raise RuntimeFailure("database_checkpoint_busy")
    return len(paths)
