"""Offline SQLite backup without opening or checkpointing the source database."""

from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

from admin_credentials import check_private, private_directory
from runtime_errors import RuntimeFailure


def require_closed(paths):
    binary = shutil.which("lsof")
    if not binary:
        raise RuntimeFailure("source_inspection_unavailable_install_lsof")
    result = subprocess.run(
        [binary, "-t", "--", *[str(p) for p in paths]], capture_output=True, timeout=10
    )
    if result.returncode == 0 and result.stdout.strip():
        raise RuntimeFailure("source_database_in_use_stop_original_service")
    if result.returncode not in (0, 1):
        raise RuntimeFailure("source_process_inspection_failed")


def backup_readonly(source, destination):
    # SQLite mode=ro may update WAL shared memory. Operate only on a verified
    # private copy of the stopped DB + sidecars, never the original directory.
    from state_migration import fingerprint

    source = Path(source)
    paths = [
        p
        for p in (
            source,
            Path(str(source) + "-wal"),
            Path(str(source) + "-shm"),
            Path(str(source) + "-journal"),
        )
        if p.exists() or p.is_symlink()
    ]
    if Path(str(source) + "-journal") in paths:
        raise RuntimeFailure("source_rollback_journal_requires_operator_recovery")
    for path in paths:
        check_private(path)
    require_closed(paths)
    before = {path: fingerprint(path) for path in paths}
    with tempfile.TemporaryDirectory(
        prefix=".sqlite-snapshot-", dir=Path(destination).parent
    ) as temp:
        temp = private_directory(Path(temp))
        for path in paths:
            if fingerprint(path, temp / path.name) != before[path]:
                raise RuntimeFailure("source_database_changed")
        uri = (temp / source.name).as_uri() + "?mode=ro"
        with (
            closing(sqlite3.connect(uri, uri=True)) as old,
            closing(sqlite3.connect(destination)) as new,
        ):
            old.backup(new)
    require_closed(paths)
    if any(fingerprint(path) != value for path, value in before.items()) or any(
        Path(str(source) + suffix).exists() and Path(str(source) + suffix) not in paths
        for suffix in ("-wal", "-shm", "-journal")
    ):
        raise RuntimeFailure("source_database_changed")


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
