"""Read-only legacy import into an empty private state directory; never starts services."""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import sqlite3

from admin_credentials import CredentialError as Failure, persist, read_private, valid_token


def parse_env(text):
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if any(c in line for c in ("$", "`", "\x00")):
            raise Failure("legacy_env_expansion_not_supported")
        parts = shlex.split(line, comments=True)
        if len(parts) != 1:
            raise Failure("legacy_env_invalid")
        key, sep, value = parts[0].partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in result:
            raise Failure("legacy_env_invalid")
        result[key] = value
    return result


def field(data, names):
    values = [data[k] for k in names if k in data]
    if not values or any(v != values[0] for v in values) or not isinstance(values[0], str):
        raise Failure("legacy_field_missing_or_conflicting")
    return values[0]


class Source:
    def __init__(self, path):
        self.path = Path(os.path.abspath(path))
        if not self.path.is_dir() or any(
            p.is_symlink() or p.is_junction() for p in (self.path, *self.path.parents)
        ):
            raise Failure("legacy_source_invalid")
        self.hashes = {}

    def read(self, names, required=True):
        for name in names:
            path = self.path / name
            if path.exists() or path.is_symlink():
                if any(p.is_symlink() or p.is_junction() for p in path.parents):
                    raise Failure("legacy_symlink")
                text = read_private(path)
                self.hashes[path] = hashlib.sha256(text.encode()).hexdigest()
                return json.loads(text) if path.suffix == ".json" else parse_env(text)
        if required:
            raise Failure("legacy_required_file_missing")
        return {}

    def unchanged(self):
        for path, digest in self.hashes.items():
            if hashlib.sha256(read_private(path).encode()).hexdigest() != digest:
                raise Failure("legacy_source_changed")


def import_legacy(source_path, target, args, runtime):
    if not source_path:
        raise Failure("legacy_source_required")
    source = Source(source_path)
    if source.path == target or source.path in target.parents or target in source.path.parents:
        raise Failure("legacy_source_target_overlap")
    if list(target.iterdir()):
        raise Failure("legacy_target_not_empty")
    config = source.read(["instance.json"], required=False)
    origin, worker = config.get("origin", args.origin), config.get("worker", args.worker)
    if origin == worker or any(
        not isinstance(v, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", v)
        for v in (origin, worker)
    ):
        raise Failure("legacy_agent_invalid")
    admin = source.read(["admin.json", "admin.env"])
    admin_token = valid_token(field(admin, ["token", "admin_token", "ROUNDTABLE_ADMIN_TOKEN"]))
    room = source.read(["room.json", "room.env"])
    room_id = field(room, ["id", "room", "room_id", "ROUNDTABLE_ROOM"])
    room_token = valid_token(field(room, ["token", "room_token", "ROUNDTABLE_ROOM_TOKEN"]))
    if not re.fullmatch(r"[a-f0-9]{24}", room_id):
        raise Failure("legacy_room_invalid")
    members = {}
    for agent in (origin, worker):
        record = source.read([agent + ".json", agent + ".env"])
        if (
            field(record, ["id", "agent", "agent_id", "ROUNDTABLE_AGENT"]) != agent
            or field(record, ["room", "room_id", "ROUNDTABLE_ROOM"]) != room_id
        ):
            raise Failure("legacy_member_scope_mismatch")
        members[agent] = valid_token(field(record, ["token", "ROUNDTABLE_TOKEN"]))
    key = source.read(
        ["tunnel/runtime-key.env", "runtime-key.env", "tunnel/key.env"], required=False
    )
    if key and not re.fullmatch(r"sk-[A-Za-z0-9_-]{16,}", key.get("CONTROL_PLANE_API_KEY", "")):
        raise Failure("legacy_runtime_key_invalid")
    events = source.read(["events.env"], required=False)
    from outbound import canonical_host, proxy_config

    hosts = config.get("event_hosts", [])
    if not hosts and events.get("ROUNDTABLE_EVENT_HOST"):
        hosts = [events["ROUNDTABLE_EVENT_HOST"]]
    hosts = [canonical_host(h) for h in hosts]
    proxy = (
        args.proxy
        if args.proxy is not None
        else config.get("proxy", events.get("ROUNDTABLE_OUTBOUND_PROXY", ""))
    )
    if proxy:
        proxy_config(proxy)
    routine = source.read(["grok-routine.json", "routine.json"], required=False)
    routine_env = None
    if routine:
        value = routine.get("environment", routine)
        url = field(value, ["url", "endpoint", "GROK_ROUTINE_URL"])
        secret = field(value, ["key", "GROK_ROUTINE_KEY"])
        from urllib.parse import urlsplit
        from grok_adapter import GrokWebhook

        host = canonical_host(urlsplit(url).hostname or "")
        GrokWebhook(url, secret, allowed_host=host)
        routine_env = {
            "GROK_ROUTINE_URL": url,
            "GROK_ROUTINE_KEY": secret,
            "GROK_ALLOWED_HOST": host,
        }
    ports = (args.server_port, args.mcp_port)
    if ports[0] == ports[1] or any(not 1 <= p <= 65535 for p in ports):
        raise Failure("invalid_ports")
    tunnel_id = "<TUNNEL_ID>"

    for name in ("tunnel/roundtable.yaml", "tunnel.yaml"):
        path = source.path / name
        if path.exists():
            text = read_private(path)
            source.hashes[path] = hashlib.sha256(text.encode()).hexdigest()
            tunnel_id = runtime.profile_tunnel_id(text)
            if tunnel_id != "<TUNNEL_ID>" and (
                not isinstance(tunnel_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", tunnel_id)
            ):
                raise Failure("legacy_tunnel_id_invalid")
            break
    stage = runtime.private_dir(target.with_name(".import-" + secrets.token_hex(12)))
    try:
        persist(stage, admin_token)
        runtime.env_save(
            stage / "room.env", {"ROUNDTABLE_ROOM": room_id, "ROUNDTABLE_ROOM_TOKEN": room_token}
        )
        for agent, token in members.items():
            runtime.env_save(
                stage / (agent + ".env"),
                {
                    "ROUNDTABLE_URL": f"http://127.0.0.1:{ports[0]}",
                    "ROUNDTABLE_ROOM": room_id,
                    "ROUNDTABLE_AGENT": agent,
                    "ROUNDTABLE_TOKEN": token,
                },
            )
        runtime.save(stage / "roundtable.db", "")
        from roundtable import Store, digest

        old_db = source.path / "roundtable.db"
        if old_db.exists():
            runtime.check_private(old_db)
            if any(Path(str(old_db) + suffix).exists() for suffix in ("-wal", "-journal")):
                raise Failure("legacy_database_requires_quiescent_backup")
            before = old_db.stat()
            with (
                sqlite3.connect(old_db.as_uri() + "?mode=ro&immutable=1", uri=True) as old,
                sqlite3.connect(stage / "roundtable.db") as new,
            ):
                old.backup(new)
            after = old_db.stat()
            if any(Path(str(old_db) + suffix).exists() for suffix in ("-wal", "-journal")) or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise Failure("legacy_source_changed")
        store = Store(str(stage / "roundtable.db"))
        try:
            if old_db.exists():
                row = store.db.execute("SELECT token FROM rooms WHERE id=?", (room_id,)).fetchone()
                if not row or row[0] != digest(room_token):
                    raise Failure("legacy_database_scope_mismatch")
                for agent, token in members.items():
                    row = store.db.execute(
                        "SELECT token FROM agents WHERE room=? AND id=?", (room_id, agent)
                    ).fetchone()
                    if not row or row[0] != digest(token):
                        raise Failure("legacy_database_scope_mismatch")
            else:
                with store.db:
                    store.db.execute(
                        "INSERT INTO rooms(id,token,name) VALUES (?,?,?)",
                        (room_id, digest(room_token), "Imported roundtable"),
                    )
                    for agent, kind in ((origin, "grok"), (worker, "dot")):
                        store.register_bot(agent, agent, kind)
                        store.db.execute(
                            "INSERT INTO agents(room,id,kind,token) VALUES (?,?,?,?)",
                            (room_id, agent, kind, digest(members[agent])),
                        )
            # Never replay an imported task's unknown external receipt history, even
            # if the operator later explicitly enables receipts or uses the CLI.
            from terminal_receipts import TerminalReceipts

            runtime.save(stage / "terminal.db", "")
            ledger = TerminalReceipts(stage / "terminal.db")
            try:
                with ledger.db:
                    ledger.db.executemany(
                        "INSERT OR IGNORE INTO terminal_delivery VALUES(?,?,?,?,?)",
                        [
                            (row["room"], row["id"], row["status"], "imported_suppressed", 0)
                            for row in store.db.execute("SELECT room,id,status FROM tasks")
                        ],
                    )
            finally:
                ledger.close()
        finally:
            store.db.close()
        if key:
            runtime.env_save(
                stage / "runtime-key.env", {"CONTROL_PLANE_API_KEY": key["CONTROL_PLANE_API_KEY"]}
            )
        if routine_env:
            runtime.write_json(
                stage / "routine.pending.json",
                {"explicit_opt_in": False, "environment": routine_env},
            )
        profile = (
            (runtime.HOME / "examples/tunnel-client.yaml")
            .read_text()
            .replace("<TUNNEL_ID>", tunnel_id)
            .replace("127.0.0.1:8766", f"127.0.0.1:{ports[1]}")
        )
        runtime.save(stage / "tunnel.yaml", profile)
        runtime.write_json(
            stage / "instance.json",
            {
                "version": 1,
                "home": str(runtime.HOME),
                "identity": secrets.token_hex(16),
                "room": room_id,
                "origin": origin,
                "worker": worker,
                "server_port": ports[0],
                "mcp_port": ports[1],
                "event_hosts": hosts,
                "events": True,
                "proxy": proxy,
            },
        )
        source.unchanged()
        if list(target.iterdir()):
            raise Failure("legacy_target_not_empty")
        os.replace(stage, target)
        return {
            "ok": True,
            "imported_members": len(members),
            "runtime_key_imported": bool(key),
            "routine_pending_approval": bool(routine_env),
            "history_imported": old_db.exists(),
            "services_started": False,
        }
    finally:
        if stage.exists():
            shutil.rmtree(stage)
