"""Stopped-instance checks shared by maintenance commands; never sends signals."""

import socket
from runtime_errors import RuntimeFailure as Failure


def require_stopped(source, config, runtime):
    for component in runtime.MANAGED:
        pidfile = source / (component + ".pid.json")
        if pidfile.exists():
            record = runtime.read_json(pidfile)
            stamp = runtime.process_stamp(record["pid"])
            if stamp:
                if record.get("stamp") != stamp or record.get("identity") != config["identity"]:
                    raise Failure("instance_pid_identity_uncertain")
                raise Failure("instance_running_use_down")
        started = source / (component + ".started.json")
        child = source / (component + ".child.json")
        if pidfile.exists() or started.exists() or child.exists():
            stop = source / (component + ".stop.json")
            if not stop.exists():
                raise Failure("instance_descendant_cleanup_unconfirmed")
            result = runtime.read_json(stop)
            if result.get("identity") != config["identity"] or result.get("cleaned") is not True:
                raise Failure("instance_descendant_cleanup_unconfirmed")
    for key in ("server_port", "mcp_port"):
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", config[key])) == 0:
                raise Failure("instance_port_in_use_stop_or_review")
