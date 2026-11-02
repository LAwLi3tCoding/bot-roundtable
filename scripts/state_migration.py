"""Explicit stopped-instance state migration. No service control or secret-store writes."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat

from admin_credentials import (
    CredentialError as Failure,
    account,
    check_private,
    private_directory,
    read_private,
    save_private,
)


@contextmanager
def file_lock(path):
    import fcntl

    if path.exists() or path.is_symlink():
        check_private(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def require_stopped(source, config, runtime):
    for component in runtime.MANAGED:
        pidfile = source / (component + ".pid.json")
        if pidfile.exists():
            record = runtime.read_json(pidfile)
            stamp = runtime.process_stamp(record["pid"])
            if stamp:
                if record.get("stamp") != stamp or record.get("identity") != config["identity"]:
                    raise Failure("migration_pid_identity_uncertain")
                raise Failure("instance_running_use_down_before_migration")
        started = source / (component + ".started.json")
        child = source / (component + ".child.json")
        if pidfile.exists() or started.exists() or child.exists():
            stop = source / (component + ".stop.json")
            if not stop.exists():
                raise Failure("migration_descendant_cleanup_unconfirmed")
            result = runtime.read_json(stop)
            if result.get("identity") != config["identity"] or result.get("cleaned") is not True:
                raise Failure("migration_descendant_cleanup_unconfirmed")
    for key in ("server_port", "mcp_port"):
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", config[key])) == 0:
                raise Failure("instance_port_in_use_stop_or_review_before_migration")


def check_directory(path):
    path = Path(path)
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise Failure("migration_symlink_directory")
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Failure("migration_private_directory_required")


def inventory(source):
    files = []
    for root, dirs, names in os.walk(source, followlinks=False):
        for name in dirs:
            check_directory(Path(root) / name)
        for name in names:
            path = Path(root) / name
            rel = path.relative_to(source).as_posix()
            info = path.lstat()
            if (
                rel == "tunnel-log.pipe"
                and stat.S_ISFIFO(info.st_mode)
                and info.st_uid == os.getuid()
                and not info.st_mode & 0o077
            ):
                continue
            check_private(path)
            if rel.endswith(("-wal", "-journal", "-shm")):
                raise Failure("migration_requires_checkpointed_offline_database")
            if rel in ("incomplete.json", "prepared.json", "recovery.json"):
                raise Failure("migration_incomplete_instance")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                raise Failure("migration_unrecognized_filename")
            files.append(rel)
    return sorted(files)


def transient(rel):
    name = Path(rel).name
    return (
        name.endswith(".lock")
        or name in (".lock", "health.url", "tunnel-child.pid")
        or any(
            name.endswith(suffix)
            for suffix in (".pid.json", ".started.json", ".child.json", ".stop.json")
        )
    )


def open_pinned(path):
    # Walk each ancestor with O_NOFOLLOW: a swapped intermediate symlink must
    # never redirect a source read outside the selected private snapshot.
    path = Path(path).absolute()
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)


def fingerprint(path, destination=None):
    check_private(path)
    fd = open_pinned(path)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_mode & 0o077
        ):
            raise Failure("migration_private_file_required")
        output = None
        try:
            if destination is not None:
                save_private(destination, "")
                outfd = os.open(destination, os.O_WRONLY | os.O_NOFOLLOW)
                output = os.fdopen(outfd, "wb")
            digest = hashlib.sha256()
            size = 0
            while chunk := source.read(256 * 1024):
                digest.update(chunk)
                size += len(chunk)
                if output:
                    output.write(chunk)
            if output:
                output.flush()
                os.fsync(output.fileno())
            after = os.fstat(source.fileno())
            final = path.stat(follow_symlinks=False)

            def identity(info):
                return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode)

            if identity(before) != identity(after) or identity(after) != identity(final):
                raise Failure("migration_source_changed")
            return {"size": size, "sha256": digest.hexdigest()}
        finally:
            if output:
                output.close()


def migrate_state(source_path, target, args, runtime):
    source = Path(os.path.abspath(source_path))
    target = Path(os.path.abspath(target))
    if not source.is_dir():
        raise Failure("migration_source_missing")
    check_directory(source)
    if source == target or source in target.parents or target in source.parents:
        raise Failure("migration_source_target_overlap")
    private_directory(target.parent)
    # One target lock serializes migrations; source's lifecycle lock excludes up/down.
    destination_lock = target.parent / (
        ".migration-" + hashlib.sha256(str(target).encode()).hexdigest() + ".lock"
    )
    if not (source / ".lock").exists():
        raise Failure("migration_source_lifecycle_lock_missing")
    with file_lock(destination_lock), file_lock(source / ".lock"):
        config = runtime.load(source)
        require_stopped(source, config, runtime)
        files = inventory(source)
        original = {rel: fingerprint(source / rel) for rel in files}
        marker_path = target / "migration.json"
        if target.exists():
            private_directory(target)
            if marker_path.exists():
                marker = json.loads(read_private(marker_path))
                if (
                    marker.get("version") != 1
                    or marker.get("source_identity") != config["identity"]
                    or marker.get("source_files") != original
                ):
                    raise Failure("migration_existing_target_mismatch")
                expected = marker.get("target_files", {})
                actual = [rel for rel in inventory(target) if rel != "migration.json"]
                if sorted(expected) != actual or any(
                    fingerprint(target / rel) != expected[rel] for rel in actual
                ):
                    raise Failure("migration_existing_target_mismatch")
                return {"ok": True, "already_migrated": True, "source_retained": True}
            if list(target.iterdir()):
                raise Failure("migration_target_not_empty")
        stage = private_directory(target.with_name(".migrate-" + secrets.token_hex(16)))
        try:
            for rel in files:
                if transient(rel):
                    continue
                copied = fingerprint(source / rel, stage / rel)
                if copied != original[rel] or fingerprint(stage / rel) != copied:
                    raise Failure("migration_copy_verification_failed")
            # Existing OS keyring entries remain in place: no secret is read or rewritten.
            admin = stage / "admin.json"
            if admin.exists():
                record = json.loads(read_private(admin))
                if record.get("backend") == "keyring":
                    binding = record.get("account_binding", account(source))
                    if not re.fullmatch(r"[a-f0-9]{64}", str(binding)) or not re.fullmatch(
                        re.escape(binding) + r"(?::[a-f0-9]{16})?", str(record.get("account", ""))
                    ):
                        raise Failure("migration_keyring_binding_invalid")
                    record["account_binding"] = binding
                    runtime.write_json(admin, record, replace=True)
            config["home"] = str(runtime.HOME)
            config["log_dir"] = str(getattr(args, "resolved_log_dir", target / "logs"))
            config["name"] = getattr(args, "name", None) or config.get("name", "default")
            runtime.write_json(stage / "instance.json", config, replace=True)
            save_private(stage / ".lock", "")
            target_files = {rel: fingerprint(stage / rel) for rel in inventory(stage)}
            if inventory(source) != files or any(
                fingerprint(source / rel) != original[rel] for rel in files
            ):
                raise Failure("migration_source_changed")
            require_stopped(source, config, runtime)
            runtime.write_json(
                stage / "migration.json",
                {
                    "version": 1,
                    "source_identity": config["identity"],
                    "source_files": original,
                    "target_files": target_files,
                },
            )
            # fsync private staging directory before atomic publication on the same volume.
            fd = os.open(stage, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            if target.exists() and list(target.iterdir()):
                raise Failure("migration_target_not_empty")
            os.replace(stage, target)
            return {
                "ok": True,
                "already_migrated": False,
                "verified_files": len(target_files),
                "source_retained": True,
                "services_started": False,
                "rerender_launchd_required": True,
            }
        finally:
            if stage.exists():
                shutil.rmtree(stage)
