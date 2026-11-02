"""Private, isolated local instance lifecycle. Never manages an unowned service."""

import argparse
from contextlib import closing, contextmanager
import getpass
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import warnings
import selectors
import shutil
import plistlib

HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOME))
from admin_credentials import (  # noqa: E402
    CredentialError,
    get_admin_token,
    rotate_admin_token,
    private_directory as credential_directory,
    check_private as credential_check,
    read_private as credential_read,
    save_private as credential_save,
)

from state_paths import StatePathError, state_dir, log_dir, instance_name, path_warnings  # noqa: E402
from private_logs import RotatingLog  # noqa: E402

AMBIENT = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
COMPONENTS = ("server", "mcp", "tunnel")
MANAGED = (*COMPONENTS, "caffeinate")
CHILDREN = {}


from runtime_errors import RuntimeFailure as Failure  # noqa: E402


def private_dir(path):
    return credential_directory(path)


def check_private(path):
    credential_check(path)


def private_read(path):
    return credential_read(path)


def save(path, text, replace=False):
    credential_save(path, text, replace)


def write_json(path, value, replace=False):
    save(path, json.dumps(value, ensure_ascii=False) + "\n", replace)


def read_json(path):
    return json.loads(private_read(path))


def env_read(path):
    result = {}
    for line in private_read(path).splitlines():
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise Failure("invalid_env_file")
        result[key] = value
    return result


def env_save(path, values, replace=False):
    if any("\n" in v or "\r" in v for v in values.values()):
        raise Failure("invalid_env_value")
    save(path, "".join(f"{k}={v}\n" for k, v in values.items()), replace)


@contextmanager
def locked(state):
    fd = os.open(state / ".lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def request(port, path, token="", data=None, method=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.request(
            method or ("POST" if data is not None else "GET"),
            path,
            json.dumps(data) if data is not None else None,
            {"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        response = conn.getresponse()
        body = response.read(1_000_001)
        if response.status not in (200, 201):
            raise Failure("local_request_rejected")
        return json.loads(body)
    finally:
        conn.close()


def load(state):
    config = read_json(state / "instance.json")
    if config.get("version") != 1:
        raise Failure("instance_schema_unsupported")
    if (state / "incomplete.json").exists():
        raise Failure("incomplete_instance_requires_operator_recovery")
    if not re.fullmatch(r"[a-f0-9]{32}", config.get("identity", "")) or not re.fullmatch(
        r"[a-f0-9]{24}", config.get("room", "")
    ):
        raise Failure("invalid_instance_identity")
    for role in ("origin", "worker"):
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", config.get(role, "")):
            raise Failure("invalid_instance_agent")
        check_private(state / (config[role] + ".env"))
    for name in ("roundtable.db", "tunnel.yaml"):
        check_private(state / name)
    if not (state / "admin.json").exists() and not (state / "admin.env").exists():
        raise Failure("admin_credential_missing")
    if (
        any(
            type(config.get(k)) is not int or not 1 <= config[k] <= 65535
            for k in ("server_port", "mcp_port")
        )
        or config["server_port"] == config["mcp_port"]
    ):
        raise Failure("invalid_instance_ports")
    from outbound import canonical_host, proxy_config

    if not isinstance(config.get("event_hosts"), list) or any(
        canonical_host(h) != h for h in config["event_hosts"]
    ):
        raise Failure("invalid_approved_hosts")
    if config["proxy"]:
        proxy_config(config["proxy"])
    return config


def setup(state, args):
    with locked(state):
        if (state / "instance.json").exists():
            config = load(state)
            room_repair = repair_room_env(state, config)
            return {
                "room_env": room_repair,
                "ok": True,
                "already_configured": True,
                "next_steps": next_steps(state),
            }
        if list(p for p in state.iterdir() if p.name != ".lock"):
            raise Failure("incomplete_or_foreign_instance_use_new_empty_directory")
        if (
            args.origin == args.worker
            or any(not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", v) for v in (args.origin, args.worker))
            or not 0 <= args.allowance <= 20
        ):
            raise Failure("invalid_agents_or_allowance")
        if (
            args.server_port is not None
            and not 1 <= args.server_port <= 65535
            or args.mcp_port is not None
            and not 1 <= args.mcp_port <= 65535
            or (args.server_port is not None and args.server_port == args.mcp_port)
        ):
            raise Failure("invalid_ports")
        # Pick distinct free loopback ports, without claiming another process's socket.
        sockets = []
        try:
            for option in ("server_port", "mcp_port"):
                if getattr(args, option) is None:
                    sock = socket.socket()
                    sock.bind(("127.0.0.1", 0))
                    sockets.append(sock)
                    setattr(args, option, sock.getsockname()[1])
        finally:
            for sock in sockets:
                sock.close()
        if args.server_port == args.mcp_port:
            raise Failure("port_selection_conflict_retry_setup")
        if (
            not 256 <= getattr(args, "log_max_bytes", 10 * 1024 * 1024) <= 1024 * 1024 * 1024
            or not 1 <= getattr(args, "log_backups", 3) <= 20
        ):
            raise Failure("invalid_log_rotation_limits")
        write_json(state / "incomplete.json", {"reason": "initialization_in_progress"})
        admin = get_admin_token(state, prefer_keyring=getattr(args, "keyring", False), environ={})
        from roundtable import Store
        from server import make_server

        save(state / "roundtable.db", "")
        store = Store(str(state / "roundtable.db"))
        server = make_server(store, admin, port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            for agent, kind in ((args.origin, "grok"), (args.worker, "dot")):
                request(
                    server.server_port,
                    "/api/bots",
                    admin,
                    {"id": agent, "name": agent, "kind": kind},
                )
            room = request(
                server.server_port,
                "/api/rooms",
                admin,
                {"name": "Local roundtable", "bots": [args.origin, args.worker]},
            )
            write_json(state / "recovery.json", room)
            env_save(
                state / "room.env",
                {"ROUNDTABLE_ROOM": room["id"], "ROUNDTABLE_ROOM_TOKEN": room["token"]},
            )
            request(
                server.server_port,
                f"/api/rooms/{room['id']}/grant",
                admin,
                {"id": args.origin, "allowance": args.allowance},
            )
            for agent in room["agent_tokens"]:
                env_save(
                    state / (agent["id"] + ".env"),
                    {
                        "ROUNDTABLE_URL": f"http://127.0.0.1:{args.server_port}",
                        "ROUNDTABLE_ROOM": room["id"],
                        "ROUNDTABLE_AGENT": agent["id"],
                        "ROUNDTABLE_TOKEN": agent["token"],
                    },
                )
            write_json(
                state / "prepared.json",
                {
                    "version": 1,
                    "home": str(HOME),
                    "name": getattr(args, "name", None) or "default",
                    "log_dir": str(getattr(args, "resolved_log_dir", state / "logs")),
                    "log_max_bytes": getattr(args, "log_max_bytes", 10 * 1024 * 1024),
                    "log_backups": getattr(args, "log_backups", 3),
                    "identity": secrets.token_hex(16),
                    "room": room["id"],
                    "origin": args.origin,
                    "worker": args.worker,
                    "server_port": args.server_port,
                    "mcp_port": args.mcp_port,
                    "event_hosts": [],
                    "events": True,
                    "proxy": "",
                },
            )
            profile = (
                (HOME / "examples/tunnel-client.yaml")
                .read_text()
                .replace("127.0.0.1:8766", f"127.0.0.1:{args.mcp_port}")
            )
            save(state / "tunnel.yaml", profile)
            (state / "incomplete.json").unlink()
            (state / "recovery.json").unlink()
            os.replace(state / "prepared.json", state / "instance.json")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.db.close()
        return {
            "ok": True,
            "already_configured": False,
            "services_running": False,
            "next_steps": next_steps(state),
        }


def child_env(state, config, component):
    # Do not inherit unrelated app credentials or accidental terminal hook settings.
    env = {
        k: v
        for k, v in os.environ.items()
        if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR")
    }
    env["PYTHONUNBUFFERED"] = "1"
    if config["proxy"]:
        env["ROUNDTABLE_OUTBOUND_PROXY"] = config["proxy"]
    if component == "caffeinate":
        return env  # No administrator, member, runtime or routine credentials.
    if component == "server":
        env["ROUNDTABLE_ADMIN_TOKEN"] = get_admin_token(state)
        routine = state / "routine.json"
        if routine.exists():
            value = read_json(routine)
            if value.get("explicit_opt_in") is not True:
                raise Failure("routine_not_explicitly_approved")
            from grok_adapter import GrokWebhook

            routine_env = value["environment"]
            if set(routine_env) != {"GROK_ROUTINE_URL", "GROK_ROUTINE_KEY", "GROK_ALLOWED_HOST"}:
                raise Failure("invalid_routine_environment")
            GrokWebhook(
                routine_env["GROK_ROUTINE_URL"],
                routine_env["GROK_ROUTINE_KEY"],
                routine_env["GROK_ALLOWED_HOST"],
            )
            env.update(routine_env)
            env.update(
                ROUNDTABLE_TERMINAL_NOTIFICATIONS="1",
                ROUNDTABLE_TERMINAL_ROOM=config["room"],
                ROUNDTABLE_TERMINAL_ORIGIN=config["origin"],
                ROUNDTABLE_TERMINAL_LEDGER=str(state / "terminal.db"),
            )
    else:
        member = env_read(state / (config["worker"] + ".env"))
        env["ROUNDTABLE_URL"] = f"http://127.0.0.1:{config['server_port']}"
        env["ROUNDTABLE_TUNNEL_AUTH_HEADER"] = "Bearer " + member["ROUNDTABLE_TOKEN"]
        if component == "mcp":
            env["ROUNDTABLE_HTTP_GRANTS"] = json.dumps(
                [
                    {
                        "room": config["room"],
                        "agent": config["worker"],
                        "token": member["ROUNDTABLE_TOKEN"],
                    }
                ]
            )
        else:
            key = env_read(state / "runtime-key.env")
            if set(key) != {"CONTROL_PLANE_API_KEY"} or not re.fullmatch(
                r"sk-[A-Za-z0-9_-]{16,}", key["CONTROL_PLANE_API_KEY"]
            ):
                raise Failure("invalid_runtime_key_environment")
            env.update(key)
    return env


def command(state, config, component):
    if component == "caffeinate":
        binary = shutil.which("caffeinate") if sys.platform == "darwin" else None
        server_pid = owned(state, config, "server")
        if not binary or not server_pid:
            raise Failure("caffeinate_requires_supported_platform_and_owned_server")
        # The verified server supervisor lives until its actual server group is cleaned.
        # -w is bound to that lifecycle; this is not a global or persistent power setting.
        return [binary, "-i", "-s", "-w", str(server_pid)]
    if component == "server":
        return [
            sys.executable,
            str(HOME / "server.py"),
            "--port",
            str(config["server_port"]),
            "--db",
            str(state / "roundtable.db"),
        ]
    if component == "mcp":
        cmd = [sys.executable, str(HOME / "mcp_http.py"), "--port", str(config["mcp_port"])]
        if config["events"]:
            cmd += ["--events-db", str(state / "events.db")]
            for host in config["event_hosts"]:
                cmd += ["--event-host", host]
        return cmd
    profile = state / "tunnel.yaml"
    private_read(profile)
    cmd = [
        "tunnel-client",
        "run",
        "--profile-file",
        str(profile),
        "--health.listen-addr",
        "127.0.0.1:0",
        "--health.url-file",
        str(state / "health.url"),
        "--pid.file",
        str(state / "tunnel-child.pid"),
        "--log.file",
        str(state / "tunnel-log.pipe"),
        "--log.http-raw-unsafe=false",
    ]
    if config["proxy"]:
        cmd += ["--control-plane.http-proxy", config["proxy"]]
    return cmd


def process_stamp(pid):
    result = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "lstart=", "-o", "command="],
        capture_output=True,
        text=True,
        timeout=3,
    )
    return (
        result.stdout.strip() if result.returncode == 0 and "<defunct>" not in result.stdout else ""
    )


def owned(state, config, component):
    path = state / (component + ".pid.json")
    if not path.exists():
        return None
    record = read_json(path)
    stamp = process_stamp(record["pid"])
    if not stamp:
        return None
    if (
        stamp != record["stamp"]
        or record["identity"] != config["identity"]
        or record["component"] != component
        or f"{Path(__file__).resolve()} _serve --state-dir {state} --component {component} --identity {config['identity']}"
        not in stamp
    ):
        raise Failure("pid_ownership_mismatch")
    return record["pid"]


def redact(line, env):
    for key, value in env.items():
        if value and any(word in key for word in ("TOKEN", "KEY", "AUTH", "GRANTS", "ROUTINE_URL")):
            line = line.replace(value, "[redacted]")
    line = re.sub(
        r"(?i)Bearer\s+[^\s\"',;]+|sk-[A-Za-z0-9_-]+|whsec_[A-Za-z0-9+/=]+", "[redacted]", line
    )
    line = re.sub(r"https?://[^\s\"'<>]+", "[url-redacted]", line)
    line = re.sub(
        r"(?i)((?:token|secret|api_key|authorization|password)\s*[=:]\s*)[^\s,;]+",
        r"\1[redacted]",
        line,
    )
    return line


def safe_log(line):
    """Persist a strict status vocabulary, never arbitrary vendor/application text."""
    match = re.search(r"callback_host_not_approved host=([a-zA-Z0-9.-]+)(?:\s|$)", line)
    if match:
        from outbound import canonical_host

        try:
            return "callback_host_not_approved host=" + canonical_host(match[1]) + "\n"
        except ValueError:
            return "callback_host_not_approved\n"
    match = re.search(r"\bevent_subscription_(created|renewed|cancelled|expired|revoked)\b", line)
    return match[0] + "\n" if match else ""


def group_live(pgid):
    """Read only process-group IDs/states, never argv/environment; leader is unreaped."""
    result = subprocess.run(
        ["ps", "-ax", "-o", "pgid=", "-o", "stat="], capture_output=True, text=True, timeout=3
    )
    if result.returncode != 0:
        raise Failure("process_group_state_unavailable")
    return any(
        len(fields := line.split()) == 2
        and fields[0] == str(pgid)
        and not fields[1].startswith("Z")
        for line in result.stdout.splitlines()
    )


def supervise(state, config, component, identity):
    if identity != config["identity"]:
        raise Failure("instance_identity_mismatch")
    os.umask(0o077)
    env = child_env(state, config, component)
    logpath = Path(config.get("log_dir", str(state / "logs"))) / (component + ".log")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    pipepath = state / "tunnel-log.pipe"
    source = None
    child = None
    with (
        RotatingLog(
            logpath, config.get("log_max_bytes", 10 * 1024 * 1024), config.get("log_backups", 3)
        ) as log,
        selectors.DefaultSelector() as selector,
    ):
        try:
            if component == "tunnel":
                if pipepath.exists() or pipepath.is_symlink():
                    info = pipepath.lstat()
                    if not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid():
                        raise Failure("invalid_tunnel_log_pipe")
                    pipepath.unlink()
                os.mkfifo(pipepath, 0o600)
                source = os.open(pipepath, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW)
                selector.register(source, selectors.EVENT_READ)
            write_json(
                state / (component + ".started.json"),
                {"identity": identity, "supervisor_pid": os.getpid()},
                replace=True,
            )
            child_command = command(state, config, component)
            child = subprocess.Popen(
                child_command,
                cwd=HOME,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            write_json(
                state / (component + ".child.json"),
                {
                    "pid": child.pid,
                    "identity": identity,
                    "command": child_command,
                },
                replace=True,
            )
            assert child.stdout is not None
            selector.register(child.stdout, selectors.EVENT_READ)
            log.write("component_started\n")
            log.flush()
            buffers: dict[int, bytes] = {}
            dropping = set()
            while not stop.is_set():
                # Do not reap the leader until process-group cleanup: its PID cannot be reused.
                status = subprocess.run(
                    ["ps", "-p", str(child.pid), "-o", "stat="],
                    capture_output=True,
                    text=True,
                    timeout=3,
                ).stdout.strip()
                if not status or status.startswith("Z"):
                    break
                for key, _ in selector.select(timeout=0.1):
                    raw = os.read(key.fd, 16384)
                    if not raw:
                        selector.unregister(key.fileobj)
                        continue
                    pending = buffers.get(key.fd, b"") + raw
                    lines = pending.split(b"\n")
                    for line in lines[:-1]:
                        if key.fd in dropping:
                            dropping.discard(key.fd)
                        elif len(line) <= 16384:
                            log.write(safe_log(line.decode("utf-8", "replace")))
                    tail = lines[-1]
                    if len(tail) > 16384:
                        dropping.add(key.fd)
                        tail = b""
                    buffers[key.fd] = tail
                    log.flush()
        finally:
            cleaned = True
            try:
                if child is not None:
                    try:
                        if group_live(child.pid):
                            os.killpg(child.pid, signal.SIGTERM)
                        # Leader remains unreaped throughout both signals; PGID cannot be reused.
                        time.sleep(0.2)
                        if group_live(child.pid):
                            os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        # Some kernels reject signalling an all-zombie group. Confirm it,
                        # otherwise retain failure state; never substitute a different signal path.
                        cleaned = not group_live(child.pid)
                    except Failure:
                        cleaned = False
                    if cleaned:
                        deadline = time.monotonic() + 3
                        while group_live(child.pid) and time.monotonic() < deadline:
                            time.sleep(0.05)
                        cleaned = not group_live(child.pid)
                    if cleaned:
                        child.wait(timeout=3)
                    if child.stdout:
                        child.stdout.close()
            except Exception:
                cleaned = False  # No raw exception text; a failed inspection is not success.
            finally:
                if source is not None:
                    os.close(source)
                    pipepath.unlink(missing_ok=True)
                write_json(
                    state / (component + ".stop.json"),
                    {"cleaned": cleaned, "identity": identity},
                    replace=True,
                )
                log.write("component_stopped\n" if cleaned else "descendant_cleanup_unconfirmed\n")
    if not cleaned:
        raise Failure("descendant_cleanup_unconfirmed")
    return child.returncode if child else 1


def free_port(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))


def ready(state, config, component):
    try:
        if component == "caffeinate":
            info = read_json(state / "caffeinate.child.json")
            expected = command(state, config, component)
            return (
                info.get("identity") == config["identity"]
                and info.get("command") == expected
                and " ".join(expected) in process_stamp(info["pid"])
            )
        if component == "server":
            member = env_read(state / (config["worker"] + ".env"))
            body = request(
                config["server_port"],
                f"/api/rooms/{config['room']}/agents/{config['worker']}/access",
                member["ROUNDTABLE_TOKEN"],
            )
            return body.get("authorized") is True and body.get("room") == config["room"]
        if component == "mcp":
            conn = http.client.HTTPConnection("127.0.0.1", config["mcp_port"], timeout=2)
            try:
                conn.request("POST", "/mcp", "{}", {"Content-Type": "application/json"})
                return conn.getresponse().status in (401, 403)
            finally:
                conn.close()
        url = urlsplit(private_read(state / "health.url").strip())
        if (
            url.scheme != "http"
            or url.hostname != "127.0.0.1"
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            return False
        conn = http.client.HTTPConnection("127.0.0.1", url.port, timeout=2)
        try:
            conn.request("GET", "/readyz")
            return conn.getresponse().status == 200
        finally:
            conn.close()
    except (OSError, ValueError, http.client.HTTPException):
        return False


def start(state, config, component):
    if owned(state, config, component):
        if not ready(state, config, component):
            raise Failure("owned_component_not_ready")
        return False
    if component in ("server", "mcp"):
        free_port(config[component + "_port"])
    outcome = state / (component + ".stop.json")
    if (
        (state / (component + ".pid.json")).exists()
        or (state / (component + ".started.json")).exists()
    ) and not outcome.exists():
        raise Failure("previous_descendant_cleanup_unconfirmed")
    if outcome.exists():
        if (
            not read_json(outcome).get("cleaned")
            or read_json(outcome).get("identity") != config["identity"]
        ):
            raise Failure("previous_descendant_cleanup_unconfirmed")
        outcome.unlink()
    (state / (component + ".started.json")).unlink(missing_ok=True)
    command(state, config, component)
    child_env(state, config, component)
    if component == "tunnel":
        for name in ("health.url", "tunnel-child.pid"):
            path = state / name
            if path.exists() or path.is_symlink():
                private_read(path)
                path.unlink()
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_serve",
        "--state-dir",
        str(state),
        "--component",
        component,
        "--identity",
        config["identity"],
    ]
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    CHILDREN[process.pid] = process
    try:
        stamp = process_stamp(process.pid)
        if not stamp:
            raise Failure("supervisor_start_failed")
        write_json(
            state / (component + ".pid.json"),
            {
                "pid": process.pid,
                "stamp": stamp,
                "identity": config["identity"],
                "component": component,
            },
            replace=True,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise Failure("component_start_failed_check_private_log")
            if ready(state, config, component):
                # macOS resolves the interpreter executable after spawn; record settled argv.
                stamp = process_stamp(process.pid)
                write_json(
                    state / (component + ".pid.json"),
                    {
                        "pid": process.pid,
                        "stamp": stamp,
                        "identity": config["identity"],
                        "component": component,
                    },
                    replace=True,
                )
                return True
            time.sleep(0.1)
        raise Failure("component_health_timeout")
    except BaseException:
        # The live Popen handle is authoritative even when PID record publication failed.
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        outcome = state / (component + ".stop.json")
        marker = state / (component + ".started.json")
        if marker.exists() and (not outcome.exists() or not read_json(outcome).get("cleaned")):
            raise Failure("startup_cleanup_unconfirmed") from None
        (state / (component + ".pid.json")).unlink(missing_ok=True)
        raise


def stop_component(state, config, component):
    pid = owned(state, config, component)
    if pid:
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not owned(state, config, component):
                break
            time.sleep(0.1)
        else:
            raise Failure("owned_process_stop_timeout_no_blind_kill")
    process = CHILDREN.pop(pid, None)
    if process is not None:
        process.wait(timeout=3)
    outcome = state / (component + ".stop.json")
    if (
        (state / (component + ".pid.json")).exists()
        or (state / (component + ".started.json")).exists()
    ) and not outcome.exists():
        raise Failure("descendant_cleanup_unconfirmed")
    if outcome.exists() and (
        not read_json(outcome).get("cleaned")
        or read_json(outcome).get("identity") != config["identity"]
    ):
        raise Failure("descendant_cleanup_unconfirmed")
    (state / (component + ".pid.json")).unlink(missing_ok=True)


def diagnostics(state, config):
    report = {
        "ok": True,
        "path_warnings": path_warnings(state, HOME),
        "rebind_required": config.get("home") != str(HOME),
        "server_url": f"http://127.0.0.1:{config['server_port']}",
        "mcp_url": f"http://127.0.0.1:{config['mcp_port']}/mcp",
        "components": {},
        "admin_environment_override_active": bool(os.environ.get("ROUNDTABLE_ADMIN_TOKEN")),
        "ambient_proxy_present": any(os.environ.get(k) for k in AMBIENT),
        "explicit_proxy_configured": bool(config["proxy"]),
        "events_enabled": config["events"],
        "approved_event_host_count": len(config["event_hosts"]),
        "valid_subscriptions": 0,
        "earliest_refresh_before": None,
    }
    for component in MANAGED:
        report["components"][component] = {
            "running": bool(owned(state, config, component)),
            "ready": ready(state, config, component),
        }
    report["sleep_prevention"] = {
        "enabled": config.get("caffeinate", True),
        "supported": sys.platform == "darwin" and bool(shutil.which("caffeinate")),
        "process_running": report["components"]["caffeinate"]["running"],
        "server_bound": report["components"]["caffeinate"]["ready"],
        "idle_sleep_requested": report["components"]["caffeinate"]["ready"],
        "system_sleep_requires_ac": True,
        "os_assertion_verified": False,
    }
    member = env_read(state / (config["worker"] + ".env"))
    dbpath = state / "events.db"
    if dbpath.exists():
        check_private(dbpath)
        principal = hashlib.sha256(member["ROUNDTABLE_TOKEN"].encode()).hexdigest()
        with sqlite3.connect(dbpath.as_uri() + "?mode=ro", uri=True) as db:
            count, expiry = db.execute(
                "SELECT COUNT(*),MIN(expires) FROM subscriptions WHERE principal=? AND expires>?",
                (principal, time.time()),
            ).fetchone()
            report["valid_subscriptions"], report["earliest_refresh_before"] = count, expiry
    try:
        check_private(state / "roundtable.db")
        # Owner-only local command; exactly this instance's room/origin.
        with sqlite3.connect((state / "roundtable.db").as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT allowance FROM agents WHERE room=? AND id=?",
                (config["room"], config["origin"]),
            ).fetchone()
            report["origin_allowance"] = row[0] if row else None
            report["origin_allowance_low"] = bool(row and row[0] <= 1)
    except Exception:
        report["origin_allowance"] = None
    from local_client import LocalClient

    try:
        origin = env_read(state / (config["origin"] + ".env"))
        client = LocalClient(
            origin["ROUNDTABLE_URL"], config["room"], config["origin"], origin["ROUNDTABLE_TOKEN"]
        )
        report["roundtrip_evidence"] = client.evidence(str(state / "roundtrip.json"))
    except Exception:
        report["roundtrip_evidence"] = {"available": False}
    return report


def hidden(prompt):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def configure_secret(state, config, kind, replace):
    path = state / ("runtime-key.env" if kind == "runtime-key" else "routine.json")
    if path.exists() or path.is_symlink():
        private_read(path)
        if not replace:
            raise Failure("existing_secret_not_overwritten")
    if kind == "runtime-key":
        value = hidden("Restricted Tunnels Read/Use runtime key (hidden): ")
        if not re.fullmatch(r"sk-[A-Za-z0-9_-]{16,}", value):
            raise Failure("runtime_key_format_invalid")
        env_save(path, {"CONTROL_PLANE_API_KEY": value}, replace)
    else:
        from grok_adapter import GrokWebhook
        from outbound import canonical_host

        url, key = (
            hidden("Approved Grok routine HTTPS URL (hidden): "),
            hidden("Routine key (hidden): "),
        )
        host = canonical_host(urlsplit(url).hostname)
        GrokWebhook(url, key, host)  # Validation only: no DNS or network.
        write_json(
            path,
            {
                "explicit_opt_in": True,
                "environment": {
                    "GROK_ROUTINE_URL": url,
                    "GROK_ROUTINE_KEY": key,
                    "GROK_ALLOWED_HOST": host,
                },
            },
            replace,
        )
    return {"ok": True, "saved": True, "takes_effect_on_next_start": True}


def render(state, output):
    output = private_dir(output)
    for component in COMPONENTS:
        data = {
            "Label": "org.roundtable." + load(state)["identity"] + "." + component,
            "ProgramArguments": [
                "/bin/sh",
                str(HOME / "scripts/up.sh"),
                "--state-dir",
                str(state),
                "--component",
                component,
            ],
            "WorkingDirectory": str(HOME),
            "EnvironmentVariables": {
                "PATH": str(Path.home() / ".local/bin")
                + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            },
            "RunAtLoad": False,
            "KeepAlive": False,
        }
        save(output / ("roundtable-" + component + ".plist"), plistlib.dumps(data).decode())
    return {"ok": True, "rendered": 3, "loaded": False}


def run_client(state, config, args):
    from local_client import LocalClient, read_json_stdin

    if args.operation in ("create", "tasks", "inbox") and (args.task_id or args.body is not None):
        raise Failure("client_argument_conflict")
    member = env_read(state / (config["origin"] + ".env"))
    client = LocalClient(
        member["ROUNDTABLE_URL"],
        config["room"],
        config["origin"],
        member["ROUNDTABLE_TOKEN"],
    )
    if args.operation == "create":
        result = client.call("create", read_json_stdin())
    elif args.operation == "roundtrip":
        result = client.roundtrip(config["worker"], str(state / "roundtrip.json"), args.timeout)
    elif args.operation == "wait":
        result = client.wait(args.task_id or "", args.timeout)
    else:
        payload = {"task_id": args.task_id} if args.task_id else None
        if args.body is not None:
            payload = dict(
                payload or {}, body=args.body, request_id="context-" + secrets.token_hex(16)
            )
        result = client.call(args.operation, payload)
    return result


def profile_tunnel_id(text):
    # Support the shipped profile's scalar ID, without evaluating YAML tags/aliases.
    in_control = False
    found = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            in_control = line.strip() == "control_plane:"
        elif in_control and line.lstrip().startswith("tunnel_id:"):
            value = line.split(":", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            found.append(value)
    if len(found) != 1:
        raise Failure("tunnel_id_placeholder")
    return found[0]


def preflight_tunnel(state):
    if not (state / "runtime-key.env").exists():
        raise Failure("runtime_key_missing")
    key = env_read(state / "runtime-key.env")
    if not key.get("CONTROL_PLANE_API_KEY"):
        raise Failure("runtime_key_missing")
    if set(key) != {"CONTROL_PLANE_API_KEY"} or not re.fullmatch(
        r"sk-[A-Za-z0-9_-]{16,}", key["CONTROL_PLANE_API_KEY"]
    ):
        raise Failure("invalid_runtime_key_environment")
    if not shutil.which("tunnel-client"):
        raise Failure("tunnel_client_not_found")
    tunnel_id = profile_tunnel_id(private_read(state / "tunnel.yaml"))
    if (
        not isinstance(tunnel_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", tunnel_id)
        or "TUNNEL_ID" in tunnel_id.upper()
        or tunnel_id.upper().startswith("YOUR_")
    ):
        raise Failure("tunnel_id_placeholder")


def open_ui(state, config, copy_token=False):
    if copy_token:
        choices = (
            [["pbcopy"]]
            if sys.platform == "darwin"
            else [["clip.exe"]]
            if sys.platform == "win32"
            else [["wl-copy"], ["xclip", "-selection", "clipboard"]]
        )
        command = next((cmd for cmd in choices if shutil.which(cmd[0])), None)
        if not command:
            return {
                "ok": False,
                "clipboard_copied": False,
                "reason": "clipboard_unavailable_use_private_credential_manager",
                "credential_record": str(state / "admin.json"),
            }
        token = get_admin_token(state)
        subprocess.run(
            command,
            input=token.encode("utf-16le" if sys.platform == "win32" else "utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=5,
        )
        return {
            "ok": True,
            "clipboard_copied": True,
            "clipboard_notice": "Clipboard may retain or sync secrets; clear after use.",
        }
    # Issuance itself requires the persistent admin credential, even on loopback.
    if sys.platform == "win32":
        return {"ok": False, "reason": "windows_manager_unsupported_use_ui_copy_token"}
    if not owned(state, config, "server") or not ready(state, config, "server"):
        raise Failure("owned_server_not_ready")
    binary = (
        "open"
        if sys.platform == "darwin"
        else "rundll32.exe"
        if sys.platform == "win32"
        else "xdg-open"
    )
    if not shutil.which(binary):
        return {
            "ok": False,
            "reason": "browser_launcher_unavailable_use_ui_copy_token",
            "credential_record": str(state / "admin.json"),
        }
    grant = request(config["server_port"], "/api/ui-login/issue", get_admin_token(state), {})
    code = grant.get("code", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", code):
        raise Failure("ui_login_issue_invalid")
    url = f"http://127.0.0.1:{config['server_port']}/#roundtable-login={code}"
    command = (
        [binary] + (["url.dll,FileProtocolHandler"] if sys.platform == "win32" else []) + [url]
    )
    subprocess.run(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=5
    )
    return {"ok": True, "opened": True, "one_time_login": True, "expires_in": grant["expires_in"]}


def next_steps(state):
    import shlex

    python = shlex.quote(sys.executable)
    script = shlex.quote(str(HOME / "scripts/local_runtime.py"))
    selected = shlex.quote(str(state))
    return [
        f"{python} {script} {operation} --state-dir {selected}"
        for operation in ("up --without-tunnel", "ui", "runtime-key", "up", "doctor")
    ]


def repair_room_env(state, config, rotate=False):
    from roundtable import digest

    path = state / "room.env"
    if path.exists():
        check_private(path)
        return {"ok": True, "already_present": True}
    pending = state / "room-token.pending.env"
    candidate = None
    if pending.exists():
        values = env_read(pending)
        if (
            set(values) != {"ROUNDTABLE_ROOM", "ROUNDTABLE_ROOM_TOKEN"}
            or values.get("ROUNDTABLE_ROOM") != config["room"]
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", values.get("ROUNDTABLE_ROOM_TOKEN", ""))
        ):
            raise Failure("invalid_pending_room_token_binding")
        candidate = values["ROUNDTABLE_ROOM_TOKEN"]
    for name in () if candidate else ("recovery.json", "admin.json"):
        if (state / name).exists():
            record = read_json(state / name)
            candidate = record.get("room_token") or (
                record.get("token") if record.get("id") == config["room"] else None
            )
            if candidate:
                break
    with closing(sqlite3.connect((state / "roundtable.db").as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT token FROM rooms WHERE id=?", (config["room"],)).fetchone()
    if not row:
        raise Failure("room_not_found")
    if candidate and digest(candidate) == row[0]:
        env_save(path, {"ROUNDTABLE_ROOM": config["room"], "ROUNDTABLE_ROOM_TOKEN": candidate})
        pending.unlink(missing_ok=True)
        return {"ok": True, "recovered": True}
    if not rotate:
        return {
            "ok": False,
            "reason": "room_token_hash_not_reversible_use_repair_room_env_rotate_room_token",
        }
    from runtime_lifecycle import require_stopped

    require_stopped(state, config, sys.modules[__name__])
    if not pending.exists():
        candidate = secrets.token_urlsafe(32)
        env_save(pending, {"ROUNDTABLE_ROOM": config["room"], "ROUNDTABLE_ROOM_TOKEN": candidate})
    else:
        candidate = env_read(pending)["ROUNDTABLE_ROOM_TOKEN"]
    with closing(sqlite3.connect(state / "roundtable.db")) as db, db:
        db.execute("UPDATE rooms SET token=? WHERE id=?", (digest(candidate), config["room"]))
    # A crash after the DB commit leaves a private recoverable pending token.
    os.replace(pending, path)
    return {"ok": True, "rotated_room_owner": True, "previous_room_owner_revoked": True}


def approve_routine(state, config):
    if (state / "routine.json").exists():
        raise Failure("routine_already_configured")
    from runtime_lifecycle import require_stopped
    from grok_adapter import GrokWebhook

    require_stopped(state, config, sys.modules[__name__])
    record = read_json(state / "routine.pending.json")
    env = record.get("environment", {})
    if set(env) != {"GROK_ROUTINE_URL", "GROK_ROUTINE_KEY", "GROK_ALLOWED_HOST"}:
        raise Failure("invalid_routine_environment")
    GrokWebhook(env["GROK_ROUTINE_URL"], env["GROK_ROUTINE_KEY"], env["GROK_ALLOWED_HOST"])
    write_json(state / "routine.json", {"explicit_opt_in": True, "environment": env})
    return {"ok": True, "approved": True, "takes_effect_on_next_start": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "setup",
            "up",
            "down",
            "status",
            "doctor",
            "runtime-key",
            "routine",
            "approve-host",
            "render-launchd",
            "client",
            "ui",
            "rotate-admin-token",
            "rebind",
            "paths",
            "approve-routine",
            "repair-room-env",
            "_serve",
        ],
    )
    parser.add_argument("--state-dir")
    parser.add_argument("--name")
    parser.add_argument("--log-max-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--log-backups", type=int, default=3)
    parser.add_argument("--origin", default="grok")
    parser.add_argument("--worker", default="dot")
    parser.add_argument("--allowance", type=int, default=20)
    parser.add_argument("--server-port", type=int)
    parser.add_argument("--mcp-port", type=int)
    parser.add_argument("--component", choices=MANAGED)
    parser.add_argument("--without-tunnel", action="store_true")
    parser.add_argument(
        "--no-caffeinate",
        action="store_true",
        help="Do not request macOS sleep assertions for this instance",
    )
    parser.add_argument("--proxy")
    parser.add_argument("--host")
    parser.add_argument("--output")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--copy-token", action="store_true")
    parser.add_argument("--rotate-room-token", action="store_true")
    parser.add_argument("--identity")
    parser.add_argument(
        "--operation",
        choices=[
            "doctor",
            "probe",
            "roundtrip",
            "wait",
            "task",
            "context",
            "create",
            "tasks",
            "inbox",
        ],
    )
    parser.add_argument("--task-id")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--body")
    parser.add_argument("--keyring", action="store_true")
    args = parser.parse_args()
    try:
        os.umask(0o077)
        args.name = instance_name(args.name)
        selected = state_dir(args.state_dir, args.name)
        args.resolved_log_dir = log_dir(
            selected,
            args.name,
            custom_state=bool(args.state_dir or os.environ.get("ROUNDTABLE_STATE_DIR")),
        )
        if args.action == "paths":
            print(json.dumps({"state_dir": str(selected), "log_dir": str(args.resolved_log_dir)}))
            return 0
        if (
            args.action == "setup"
            and not (
                args.state_dir or os.environ.get("ROUNDTABLE_STATE_DIR") or args.name != "default"
            )
            and not selected.exists()
            and (HOME / "data/local").exists()
        ):
            raise Failure("legacy_state_detected_manual_transfer_see_STORAGE")
        if args.action != "setup" and not (selected / "instance.json").exists():
            import shlex

            print(
                json.dumps(
                    {
                        "ok": False,
                        "configured": False,
                        "reason": "not_configured_run_setup",
                        "setup_command": shlex.join(
                            [
                                sys.executable,
                                str(HOME / "scripts/setup-local.py"),
                                "--state-dir",
                                str(selected),
                            ]
                        ),
                        "path_warnings": path_warnings(selected, HOME),
                    }
                )
            )
            return 0 if args.action in ("status", "doctor") else 1
        state = private_dir(selected)
        if args.action == "setup":
            result = setup(state, args)
        else:
            config = load(state)
            if args.action == "_serve":
                return supervise(state, config, args.component, args.identity)
            if args.action == "client":
                # Long network waits must not prevent status, cancellation or shutdown.
                print(json.dumps(run_client(state, config, args)))
                return 0
            with locked(state):
                if args.action in ("up", "approve-host"):
                    if args.proxy is not None:
                        from outbound import proxy_config

                        proxy_config(args.proxy)
                        if (
                            any(owned(state, config, c) for c in COMPONENTS)
                            and args.proxy != config["proxy"]
                        ):
                            raise Failure("stop_instance_before_proxy_change")
                        config["proxy"] = args.proxy
                    if args.action == "approve-host":
                        from outbound import canonical_host

                        config["event_hosts"] = sorted(
                            set(config["event_hosts"] + [canonical_host(args.host)])
                        )
                    write_json(state / "instance.json", config, replace=True)
                if args.action == "rebind":
                    from runtime_lifecycle import require_stopped

                    require_stopped(state, config, sys.modules[__name__])
                    config["home"] = str(HOME)
                    write_json(state / "instance.json", config, replace=True)
                    result = {"ok": True, "rebound": True, "rerender_launchd_required": True}
                elif args.action == "up":
                    if config.get("home") != str(HOME):
                        raise Failure("code_location_changed_run_rebind")
                    if not args.without_tunnel and args.component in (None, "tunnel"):
                        preflight_tunnel(state)
                    if not config["proxy"] and any(os.environ.get(k) for k in AMBIENT):
                        raise Failure("explicit_outbound_proxy_required")
                    selected = (
                        [args.component]
                        if args.component
                        else list(COMPONENTS[:2] if args.without_tunnel else COMPONENTS)
                    )
                    started = []
                    sleep_state: dict[str, object] = {"state": "unchanged"}
                    if "server" in selected:
                        config["caffeinate"] = not args.no_caffeinate
                        write_json(state / "instance.json", config, replace=True)
                        if args.no_caffeinate:
                            stop_component(state, config, "caffeinate")
                            sleep_state = {"state": "disabled"}
                        elif sys.platform != "darwin":
                            sleep_state = {"state": "skipped", "reason": "non_macos"}
                        elif not shutil.which("caffeinate"):
                            sleep_state = {"state": "skipped", "reason": "binary_unavailable"}
                        else:
                            selected.insert(selected.index("server") + 1, "caffeinate")
                            sleep_state = {"state": "requested", "system_sleep_requires_ac": True}
                    try:
                        for component in selected:
                            if start(state, config, component):
                                started.append(component)
                    except Exception:
                        for component in reversed(started):
                            stop_component(state, config, component)
                        raise
                    result = {"ok": True, "started": started, "sleep_prevention": sleep_state}
                elif args.action == "down":
                    for component in (
                        [args.component] if args.component else ("tunnel", "mcp", "server")
                    ):
                        if component == "server":
                            stop_component(state, config, "caffeinate")
                        stop_component(state, config, component)
                    from runtime_lifecycle import require_stopped
                    from sqlite_maintenance import checkpoint_state

                    checkpointed = 0
                    if args.component is None:
                        require_stopped(state, config, sys.modules[__name__])
                        checkpointed = checkpoint_state(state)
                    result = {"ok": True, "checkpointed_databases": checkpointed}
                elif args.action in ("status", "doctor"):
                    result = diagnostics(state, config)
                elif args.action == "ui":
                    result = open_ui(state, config, args.copy_token)
                elif args.action == "approve-routine":
                    result = approve_routine(state, config)
                elif args.action == "repair-room-env":
                    result = repair_room_env(state, config, args.rotate_room_token)
                elif args.action == "rotate-admin-token":
                    if any(owned(state, config, c) for c in MANAGED):
                        raise Failure("stop_instance_before_admin_rotation")
                    result = rotate_admin_token(state, prefer_keyring=args.keyring)
                elif args.action in ("runtime-key", "routine"):
                    result = configure_secret(state, config, args.action, args.replace)
                elif args.action == "approve-host":
                    result = {
                        "ok": True,
                        "approved_host_count": len(config["event_hosts"]),
                        "restart_mcp_required": True,
                    }
                else:
                    result = render(state, args.output or state / "launchd")
        print(json.dumps(result))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": str(exc)
                    if isinstance(exc, (Failure, CredentialError, StatePathError))
                    else "local_operation_failed",
                    "error_type": type(exc).__name__,
                    "secrets_included": False,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
