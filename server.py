"""HTTP boundary; credentials are supplied in Authorization, never URLs."""

import argparse
import hmac
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from roundtable import Problem, Store

STATIC = Path(__file__).parent / "static"


def make_server(store, admin, host="127.0.0.1", port=8765):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)  # Covers request-line and header parsing too.

        def log_message(self, *_args):
            pass  # Do not log paths, payloads or Authorization headers.

        def respond(self, status, data, mime="application/json"):
            payload = (
                json.dumps(data, ensure_ascii=False).encode()
                if mime == "application/json"
                else data
            )
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self.handle_request("GET")

        def do_POST(self):
            self.handle_request("POST")

        def handle_request(self, method):
            try:
                host_header = self.headers.get("Host", "")
                allowed = {
                    f"127.0.0.1:{cast(ThreadingHTTPServer, self.server).server_port}",
                    f"localhost:{cast(ThreadingHTTPServer, self.server).server_port}",
                }
                if host_header not in allowed:
                    raise Problem(403, "Host rejected; this MVP is loopback-only")
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://{h}" for h in allowed}:
                    raise Problem(403, "Origin rejected")
                path = urlsplit(self.path).path
                if method == "GET" and path in ("/", "/app.js", "/i18n.js", "/style.css"):
                    file, mime = {
                        "/": ("index.html", "text/html; charset=utf-8"),
                        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                        "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
                        "/style.css": ("style.css", "text/css; charset=utf-8"),
                    }[path]
                    return self.respond(200, (STATIC / file).read_bytes(), mime)
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                body = {}
                if method == "POST":
                    if self.headers.get("Transfer-Encoding"):
                        raise Problem(400, "Transfer encoding unsupported")
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 32768:
                        raise Problem(413, "JSON body must be 1–32768 bytes")
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise Problem(400, "Expected JSON object")
                # Authenticate and execute under one store lock, so a revoked
                # membership cannot act with a previously validated token.
                # Parse input and write responses outside this critical section.
                with store.lock:
                    status, result = self.dispatch(method, path, token, body)
                return self.respond(status, result)
            except Problem as exc:
                self.respond(exc.status, {"error": str(exc)})
            except (ValueError, TypeError):
                self.respond(400, {"error": "Invalid JSON or field type"})
            except (OSError, TimeoutError):
                self.close_connection = True
            except Exception:
                logging.error("request_failed")
                self.respond(500, {"error": "Internal server error"})

        def dispatch(self, method, path, token, body):
            if path in ("/api/rooms", "/api/bots"):
                if not hmac.compare_digest(token, admin):
                    raise Problem(403, "Admin credential required")
                if method == "GET":
                    return (200, store.list_rooms() if path == "/api/rooms" else store.registry())
                if path == "/api/bots":
                    return (
                        201,
                        store.register_bot(
                            body.get("id"),
                            body.get("name"),
                            body.get("kind"),
                            body.get("description", ""),
                        ),
                    )
            if path == "/api/rooms" and method == "POST":
                if not hmac.compare_digest(token, admin):
                    raise Problem(403, "Admin credential required")
                return (201, store.create_group(body.get("name"), body.get("bots")))
            parts = path.strip("/").split("/")
            if len(parts) < 3 or parts[:2] != ["api", "rooms"]:
                raise Problem(404, "Not found")
            room = parts[2]
            if len(parts) >= 6 and parts[3] == "agents":
                agent = parts[4]
                store.authorize(room, token, agent)
                if len(parts) == 6 and parts[5] == "access" and method == "GET":
                    return (200, {"authorized": True, "room": room, "agent": agent})
                if parts[5] == "peer":
                    if len(parts) == 6 and method == "GET":
                        return (200, store.state(room))
                    if len(parts) == 7 and method == "POST" and parts[6] == "runs":
                        return (
                            200,
                            store.start(
                                room,
                                body.get("body"),
                                body.get("targets"),
                                body.get("budget"),
                                body.get("request_id"),
                                actor="bot:" + agent,
                            ),
                        )
                    if len(parts) == 7 and method == "POST" and parts[6] == "stop":
                        store.stop_peer(room, agent)
                        return (200, {"stopped": True})
                    raise Problem(404, "Not found")
                if len(parts) == 6 and parts[5] == "inbox" and method == "GET":
                    return (200, store.inbox(room, agent))
                if len(parts) == 6 and parts[5] == "reply" and method == "POST":
                    return (
                        200,
                        store.reply(
                            room,
                            agent,
                            body.get("job_id"),
                            body.get("body"),
                            body.get("failed", False),
                        ),
                    )
                raise Problem(404, "Not found")
            if not hmac.compare_digest(token, admin):
                store.authorize(room, token)
            store.state(room)  # Verify existence even for an admin credential.
            if len(parts) == 3 and method == "GET":
                return (200, store.state(room))
            if len(parts) == 4 and method == "POST":
                if parts[3] == "settings":
                    return (200, store.settings(room, body.get("name"), body.get("lead", "")))
                if parts[3] == "join":
                    return (201, store.join(room, body.get("id")))
                if parts[3] == "remove":
                    store.remove_agent(room, body.get("id"))
                    return (200, {"removed": True})
                if parts[3] == "grant":
                    return (200, store.grant(room, body.get("id"), body.get("allowance")))
                if parts[3] == "runs":
                    return (
                        200,
                        store.start(
                            room,
                            body.get("body"),
                            body.get("targets"),
                            body.get("budget"),
                            body.get("request_id"),
                        ),
                    )
                if parts[3] == "stop":
                    store.stop(room)
                    return (200, {"stopped": True})
                if parts[3] == "agents":
                    return (201, store.add_agent(room, body.get("id"), body.get("kind", "mailbox")))
            raise Problem(404, "Not found")

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default="data/roundtable.db")
    args = parser.parse_args()
    admin = os.environ.get("ROUNDTABLE_ADMIN_TOKEN", "")
    if len(admin) < 32:
        parser.error("Set ROUNDTABLE_ADMIN_TOKEN to a random secret of at least 32 characters")
    os.umask(0o077)
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    server = make_server(store, admin, port=args.port)
    stop = threading.Event()

    def tick():
        while not stop.wait(0.5):
            store.demo_tick()

    thread = threading.Thread(target=tick, daemon=True)
    thread.start()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.info("Listening at http://127.0.0.1:%s", args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        thread.join()
        server.server_close()
        store.db.close()


if __name__ == "__main__":
    main()
