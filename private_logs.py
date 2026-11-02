"""Single-writer private bounded logs; no raw vendor text is accepted by callers."""

import os
from pathlib import Path

from admin_credentials import CredentialError, check_private, private_directory


class RotatingLog:
    def __init__(self, path, max_bytes=10 * 1024 * 1024, backups=3):
        if (
            type(max_bytes) is not int
            or not 256 <= max_bytes <= 1024 * 1024 * 1024
            or type(backups) is not int
            or not 1 <= backups <= 20
        ):
            raise CredentialError("invalid_log_rotation_limits")
        self.path = Path(path)
        private_directory(self.path.parent)
        self.max_bytes, self.backups = max_bytes, backups
        self.lock_fd = None
        self.fd = None

    def __enter__(self):
        import fcntl

        lock = self.path.with_name(self.path.name + ".lock")
        if lock.exists() or lock.is_symlink():
            check_private(lock)
        self.lock_fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._open()
        except BaseException:
            os.close(self.lock_fd)
            self.lock_fd = None
            raise
        return self

    def _open(self):
        if self.path.exists() or self.path.is_symlink():
            check_private(self.path)
        self.fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        info = os.fstat(self.fd)
        if info.st_mode & 0o077 or info.st_uid != os.getuid():
            os.close(self.fd)
            self.fd = None
            raise CredentialError("private_log_required")

    def write(self, text):
        if not text:
            return
        raw = text.encode()
        if len(raw) > self.max_bytes:
            raw = b"log_record_oversize_dropped\n"
        assert self.fd is not None
        if os.fstat(self.fd).st_size + len(raw) > self.max_bytes:
            # Validate every candidate before any rename; never follow links.
            for path in [self.path] + [
                Path(str(self.path) + f".{i}") for i in range(1, self.backups + 1)
            ]:
                if path.exists() or path.is_symlink():
                    check_private(path)
            os.close(self.fd)
            self.fd = None
            for index in range(self.backups, 1, -1):
                old = Path(str(self.path) + f".{index - 1}")
                if old.exists():
                    os.replace(old, Path(str(self.path) + f".{index}"))
            os.replace(self.path, Path(str(self.path) + ".1"))
            self._open()
        assert self.fd is not None
        os.write(self.fd, raw)

    def flush(self):
        if self.fd is not None:
            os.fsync(self.fd)

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
