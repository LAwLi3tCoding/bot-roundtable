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
                if record.get("identity") != config["identity"]:
                    raise Failure("instance_pid_identity_uncertain")
                if record.get("stamp") == stamp:
                    raise Failure("instance_running_use_down")
                # Stamp mismatch means the original supervisor is gone; do not
                # signal the process now using that pid.
        runtime.resolve_unconfirmed_cleanup(
            source,
            config,
            component,
            "instance_descendant_cleanup_unconfirmed",
            include_child=True,
        )
    for key in ("server_port", "mcp_port"):
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", config[key])) == 0:
                raise Failure("instance_port_in_use_stop_or_review")
