"""Explicit owner allowance change, with an inherited admin environment reference."""

import argparse
import http.client
import json
import os
import re
from urllib.parse import urlsplit


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["allowance"])
    p.add_argument("room")
    p.add_argument("agent")
    p.add_argument("amount", type=int, choices=range(21))
    a = p.parse_args()
    connection = None
    try:
        url = urlsplit(os.environ.get("ROUNDTABLE_URL", "http://127.0.0.1:8765"))
        if (
            url.scheme != "http"
            or url.hostname not in ("localhost", "127.0.0.1")
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
        ):
            raise ValueError()
        if not re.fullmatch(r"[a-f0-9]{24}", a.room) or not re.fullmatch(
            r"[a-z][a-z0-9-]{1,39}", a.agent
        ):
            raise ValueError()
        connection = http.client.HTTPConnection(url.hostname, url.port or 8765, timeout=10)
        connection.request(
            "POST",
            f"/api/rooms/{a.room}/grant",
            json.dumps({"id": a.agent, "allowance": a.amount}),
            {
                "Authorization": "Bearer " + os.environ["ROUNDTABLE_ADMIN_TOKEN"],
                "Content-Type": "application/json",
            },
        )
        status = connection.getresponse().status
        print(json.dumps({"ok": status == 200, "status": status}))
        return 0 if status == 200 else 1
    except Exception:
        print('{"ok":false,"reason":"allowance_update_failed"}')
        return 1
    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
