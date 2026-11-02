"""Persistent administrator credentials. Secret values never appear in diagnostics."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess

WINDOWS = os.name == "nt"
SERVICE = "bot-roundtable-admin"


class CredentialError(ValueError):
    pass


def valid_token(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", value):
        raise CredentialError("admin_token_invalid")
    return value


def windows_acl(path, create=False):
    # Fixed script; the path is data in an environment variable, never script text.
    script = r"""
$ErrorActionPreference = 'Stop'
$p = $env:ROUNDTABLE_ACL_PATH
$item = Get-Item -LiteralPath $p -Force
if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'reparse' }
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
if ($env:ROUNDTABLE_ACL_CREATE -eq '1') {
  if ($item.PSIsContainer) {
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
  } else {
    $acl = New-Object Security.AccessControl.FileSecurity
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','Allow')
  }
  $acl.SetOwner($sid)
  $acl.SetAccessRuleProtection($true,$false)
  $acl.AddAccessRule($rule)
  Set-Acl -LiteralPath $p -AclObject $acl
}
$acl = Get-Acl -LiteralPath $p
if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) { throw 'owner' }
$rules = @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if ($rules.Count -eq 0) { throw 'empty' }
foreach ($r in $rules) {
  if ($r.IdentityReference.Value -ne $sid.Value -or $r.AccessControlType -ne 'Allow') { throw 'foreign' }
}
[Console]::Write('private_acl_verified')
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env=dict(
                os.environ,
                ROUNDTABLE_ACL_PATH=str(path),
                ROUNDTABLE_ACL_CREATE="1" if create else "0",
            ),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode or result.stdout.strip() != "private_acl_verified":
            raise CredentialError("private_acl_unavailable")
    except (OSError, subprocess.SubprocessError):
        raise CredentialError("private_acl_unavailable") from None


def private_directory(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise CredentialError("symlink_directory")
    missing = []
    ancestor = path
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    for directory in reversed(missing):
        created = False
        try:
            directory.mkdir(mode=0o700)
            created = True
        except FileExistsError:
            if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
                raise CredentialError("symlink_directory") from None
        if WINDOWS:
            windows_acl(directory, create=created)
        elif directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
            raise CredentialError("private_directory_required")
    if WINDOWS:
        windows_acl(path)
    elif path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise CredentialError("private_directory_required")
    return path


def check_private(path):
    path = Path(path)
    if path.is_symlink():
        raise CredentialError("symlink_file")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise CredentialError("private_file_required")
    if WINDOWS:
        windows_acl(path)
    elif info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise CredentialError("private_file_required")


def windows_read_fd(path):
    # Pin the final object against replacement while its ACL is checked.
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise CredentialError("private_file_unavailable")
    try:
        if any(p.is_symlink() or p.is_junction() for p in (Path(path), *Path(path).parents)):
            raise CredentialError("symlink_file")
        windows_acl(path)
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)  # type: ignore[attr-defined]
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    return fd


def read_private(path):
    check_private(path)
    fd = windows_read_fd(path) if WINDOWS else os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or (
            not WINDOWS and (info.st_uid != os.getuid() or info.st_mode & 0o077)
        ):
            raise CredentialError("private_file_required")
        return file.read(1_000_001)


def save_private(path, value, replace=False):
    path = Path(path)
    private_directory(path.parent)
    if path.exists() or path.is_symlink():
        check_private(path)
        if not replace:
            raise CredentialError("existing_file_not_overwritten")
    temp = path.with_name("." + path.name + "." + secrets.token_hex(8))
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        # Directory ACL already excludes everyone else before this empty file exists.
        if WINDOWS:
            windows_acl(temp, create=True)
        with os.fdopen(fd, "w") as file:
            fd = -1
            file.write(value)
            file.flush()
            os.fsync(file.fileno())
        if replace:
            os.replace(temp, path)
        else:
            os.link(temp, path)
            temp.unlink()
    finally:
        if fd != -1:
            os.close(fd)
        temp.unlink(missing_ok=True)


@contextmanager
def private_lock(state):
    path = state / ".admin.lock"
    if not path.exists():
        try:
            save_private(path, "0")
        except (FileExistsError, CredentialError):
            if not path.exists():
                raise
            check_private(path)
    check_private(path)
    with open(path, "r+b") as lock:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def trusted_keyring():
    try:
        import importlib

        backend = importlib.import_module("keyring").get_keyring()
        if (
            backend.__class__.__module__
            not in {
                "keyring.backends.macOS",
                "keyring.backends.SecretService",
                "keyring.backends.Windows",
            }
            or backend.priority <= 0
        ):
            return None
        return backend
    except Exception:
        return None


def account(state):
    return hashlib.sha256(str(state.resolve()).encode()).hexdigest()


def stored_token(state):
    path = state / "admin.json"
    if not path.exists():
        legacy = state / "admin.env"
        if legacy.exists():
            raw = read_private(legacy).strip()
            prefix = "ROUNDTABLE_ADMIN_TOKEN="
            if not raw.startswith(prefix):
                raise CredentialError("legacy_admin_invalid")
            return valid_token(raw[len(prefix) :])
        return None
    try:
        record = json.loads(read_private(path))
        if record.get("version") != 1:
            raise CredentialError("admin_record_invalid")
        if record.get("backend") == "file":
            return valid_token(record.get("token"))
        if not re.fullmatch(r"[a-f0-9]{64}", str(record.get("account_binding", account(state)))):
            raise CredentialError("admin_record_invalid")
        if record.get("backend") != "keyring" or not re.fullmatch(
            re.escape(record.get("account_binding", account(state))) + r"(?::[a-f0-9]{16})?",
            str(record.get("account", "")),
        ):
            raise CredentialError("admin_record_invalid")
        backend = trusted_keyring()
        if backend is None:
            raise CredentialError("admin_keyring_unavailable")
        try:
            value = backend.get_password(SERVICE, record["account"])
            return valid_token(value)
        except Exception:
            raise CredentialError("admin_keyring_unavailable") from None
    except (json.JSONDecodeError, AttributeError):
        raise CredentialError("admin_record_invalid") from None


def persist(state, token, prefer_keyring=False, replace=False, require_keyring=False):
    valid_token(token)
    record = {"version": 1, "backend": "file", "token": token}
    backend = trusted_keyring() if prefer_keyring else None
    if require_keyring and backend is None:
        raise CredentialError("admin_keyring_unavailable")
    if backend is not None:
        # A unique versioned account avoids changing a live key before metadata publication.
        # Existing records remain authoritative on any error; never silently regenerate them.
        name = account(state)
        try:
            old = backend.get_password(SERVICE, name)
            if old is not None:
                if not replace:
                    raise CredentialError("untracked_keyring_record_requires_review")
                # Rotation uses a new account name, recorded explicitly below.
                name = name + ":" + secrets.token_hex(8)
            backend.set_password(SERVICE, name, token)
            if backend.get_password(SERVICE, name) != token:
                raise CredentialError("admin_keyring_write_unconfirmed")
            record = {"version": 1, "backend": "keyring", "account": name}
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("admin_keyring_write_failed") from None
    save_private(state / "admin.json", json.dumps(record) + "\n", replace=replace)
    return record["backend"]


def get_admin_token(state, *, prefer_keyring=False, environ=None):
    environ = os.environ if environ is None else environ
    override = environ.get("ROUNDTABLE_ADMIN_TOKEN")
    if override:
        if len(override) < 32 or any(c in override for c in "\r\n\x00"):
            raise CredentialError("admin_token_invalid")
        return override  # Preserve existing environment token syntax; no writeback.
    state = private_directory(state)
    with private_lock(state):
        existing = stored_token(state)
        if existing is not None:
            return existing
        value = secrets.token_urlsafe(48)
        persist(state, value, prefer_keyring)
        return value


def rotate_admin_token(state, *, prefer_keyring=False, environ=None):
    environ = os.environ if environ is None else environ
    if environ.get("ROUNDTABLE_ADMIN_TOKEN"):
        raise CredentialError("admin_environment_override_active")
    state = private_directory(state)
    with private_lock(state):
        stored_token(state)  # A locked/missing existing keyring credential is not a new identity.
        require_keyring = (state / "admin.json").exists() and json.loads(
            read_private(state / "admin.json")
        ).get("backend") == "keyring"
        old_record = (
            json.loads(read_private(state / "admin.json"))
            if (state / "admin.json").exists()
            else {}
        )
        prefer_keyring = prefer_keyring or require_keyring
        value = secrets.token_urlsafe(48)
        backend = persist(
            state,
            value,
            prefer_keyring,
            replace=(state / "admin.json").exists(),
            require_keyring=require_keyring,
        )
        cleanup = "not_needed"
        if old_record.get("backend") == "keyring":
            old_backend = trusted_keyring()
            try:
                if old_backend is None:
                    raise CredentialError("admin_keyring_unavailable")
                old_backend.delete_password(SERVICE, old_record["account"])
                cleanup = "deleted"
            except Exception:
                cleanup = "failed_manual_cleanup_required"
    return {"ok": True, "backend": backend, "restart_required": True, "old_keyring_entry": cleanup}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "rotate-admin-token"])
    from state_paths import state_dir

    parser.add_argument("--state-dir", default=str(state_dir() / "admin-credentials"))
    parser.add_argument(
        "--keyring", action="store_true", help="Prefer an installed trusted OS keyring"
    )
    args = parser.parse_args()
    try:
        if args.command == "rotate-admin-token":
            result = rotate_admin_token(args.state_dir, prefer_keyring=args.keyring)
        else:
            get_admin_token(args.state_dir, prefer_keyring=args.keyring)
            result = {"ok": True, "ready": True}
        print(json.dumps(result))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": str(exc)
                    if isinstance(exc, CredentialError)
                    else "credential_operation_failed",
                    "error_type": type(exc).__name__,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
