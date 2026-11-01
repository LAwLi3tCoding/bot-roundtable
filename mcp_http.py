"""Authenticated MCP Streamable HTTP gateway. Loopback only; no OAuth issuer fiction."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import http.client
import json
import os
import re
from dataclasses import dataclass
from starlette.types import ASGIApp
from urllib.parse import urlsplit

import uvicorn
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import JSONResponse

from mcp_bridge import build_bridge


@dataclass(frozen=True)
class Grant:
    room: str
    agent: str
    token: str


def parse_grants(value: str) -> list[Grant]:
    data = json.loads(value)
    if not isinstance(data, list) or not 1 <= len(data) <= 100:
        raise ValueError("Configure 1–100 explicit bot grants")
    grants = []
    seen = set()
    for item in data:
        if not isinstance(item, dict) or set(item) != {"room", "agent", "token"}:
            raise ValueError("Each grant needs exactly room, agent and token")
        room, agent, token = item["room"], item["agent"], item["token"]
        if not isinstance(room, str) or not re.fullmatch(r"[a-f0-9]{24}", room):
            raise ValueError("Invalid room ID")
        if (
            not isinstance(agent, str)
            or not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", agent)
            or agent == "user"
        ):
            raise ValueError("Only explicit bot identities may use HTTP")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            raise ValueError("Use an existing scoped agent token")
        if token in seen:
            raise ValueError("A token cannot select multiple identities")
        seen.add(token)
        grants.append(Grant(room, agent, token))
    return grants


class ScopedVerifier(TokenVerifier):
    def __init__(self, base: str, grants: list[Grant]):
        parsed = urlsplit(base)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost")
            or parsed.path not in ("", "/")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Backend must be a loopback HTTP origin")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 8765
        self.grants = {hashlib.sha256(g.token.encode()).hexdigest(): g for g in grants}

    def grant_for(self, token: str) -> Grant | None:
        return self.grants.get(hashlib.sha256(token.encode()).hexdigest())

    def still_authorized(self, grant: Grant) -> bool:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(
                "GET",
                f"/api/rooms/{grant.room}/agents/{grant.agent}/access",
                headers={"Authorization": "Bearer " + grant.token},
            )
            response = connection.getresponse()
            # Do not read or log room contents to validate the credential.
            return response.status == 200
        except (OSError, http.client.HTTPException):
            return False
        finally:
            connection.close()

    async def verify_token(self, token: str) -> AccessToken | None:
        grant = self.grant_for(token)
        if grant is None or not await asyncio.to_thread(self.still_authorized, grant):
            return None
        return AccessToken(
            token=token, client_id=f"{grant.room}:{grant.agent}", scopes=["roundtable"]
        )

    def identity(self) -> tuple[str, str, str]:
        access = get_access_token()
        grant = self.grant_for(access.token) if access else None
        if grant is None:
            raise ValueError("Authenticated bot grant required")
        return grant.room, grant.token, grant.agent


class HTTPAuthOnly:
    """Apply the SDK's auth guard only to HTTP; forward lifespan normally."""

    def __init__(self, app):
        self.app = app
        self.protected = RequireAuthMiddleware(app, ["roundtable"])

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            await self.protected(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await self.app(scope, receive, send)


class OriginGate:
    """Reject host/origin confusion before credentials or backend requests are processed."""

    def __init__(self, app, hosts: list[str], origins: list[str], expected_bearer: str = ""):
        self.expected_bearer = expected_bearer
        self.app, self.hosts, self.origins = app, set(hosts), set(origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = scope.get("headers", [])
            hosts = [v.decode("latin1") for k, v in headers if k.lower() == b"host"]
            origins = [v.decode("latin1") for k, v in headers if k.lower() == b"origin"]
            authorizations = [v for k, v in headers if k.lower() == b"authorization"]
            if self.expected_bearer and (
                len(authorizations) != 1
                or not hmac.compare_digest(authorizations[0], self.expected_bearer.encode())
            ):
                await JSONResponse(
                    {
                        "error": "tunnel_authorization_mismatch",
                        "hint": "Check connector forwarded Authorization override; keep authentication enabled",
                    },
                    status_code=403,
                )(scope, receive, send)
                return
            if (
                len(hosts) != 1
                or hosts[0] not in self.hosts
                or len(origins) > 1
                or len(authorizations) > 1
                or (origins and origins[0] not in self.origins)
            ):
                await JSONResponse(
                    {"error": "Ambiguous authentication, Host or Origin rejected"}, status_code=403
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_http_app(
    base: str,
    grants_json: str,
    port: int = 8766,
    public_url: str = "",
    events_db: str = "",
    event_hosts: list[str] | None = None,
    event_transport=None,
    expected_bearer: str = "",
):
    grants = parse_grants(grants_json)
    verifier = ScopedVerifier(base, grants)
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
    origins = ["http://" + host for host in hosts]
    if public_url:
        public = urlsplit(public_url)
        if (
            public.scheme != "https"
            or not public.hostname
            or public.username
            or public.password
            or public.path != "/mcp"
            or public.query
            or public.fragment
            or "*" in public.netloc
        ):
            raise ValueError("Public URL must be an exact HTTPS /mcp URL without credentials")
        hosts.append(public.netloc)
        origins.append("https://" + public.netloc)
    first = grants[0]
    bridge = build_bridge(
        base,
        first.room,
        first.token,
        first.agent,
        identity_resolver=verifier.identity,
        mcp_options={
            "stateless_http": True,
            "json_response": True,
            "max_request_body_size": 32768,
            "transport_security": TransportSecuritySettings(
                enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
            ),
        },
    )
    protocol_app: ASGIApp = bridge.streamable_http_app()
    if events_db:
        from mcp_events import EventBroker, EventsHTTP
        from event_delivery import CallbackTransport

        broker = EventBroker(
            events_db, verifier, event_transport or CallbackTransport(event_hosts or [])
        )
        protocol_app = EventsHTTP(protocol_app, broker)
    # SDK auth context is propagated into tool execution; each request obtains
    # its own identity. Stateless transport prevents cross-principal session reuse.
    secured = AuthenticationMiddleware(
        AuthContextMiddleware(HTTPAuthOnly(protocol_app)), backend=BearerAuthBackend(verifier)
    )
    return OriginGate(secured, hosts, origins, expected_bearer)


def main():
    parser = argparse.ArgumentParser(description="Authenticated local MCP HTTP gateway")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--public-url",
        default="",
        help="Exact external HTTPS /mcp URL to allow behind a trusted proxy; does not change the loopback bind",
    )
    parser.add_argument(
        "--events-db", default="", help="Opt-in private subscription/outbox SQLite path"
    )
    parser.add_argument(
        "--event-host",
        action="append",
        default=[],
        help="Exact operator-approved callback hostname; repeat as needed",
    )
    args = parser.parse_args()
    try:
        app = build_http_app(
            os.environ.get("ROUNDTABLE_URL", "http://127.0.0.1:8765"),
            os.environ["ROUNDTABLE_HTTP_GRANTS"],
            args.port,
            args.public_url,
            args.events_db,
            args.event_host,
            expected_bearer=os.environ.get("ROUNDTABLE_TUNNEL_AUTH_HEADER", ""),
        )
    except (KeyError, ValueError):
        parser.error("Invalid or missing gateway configuration; no credentials are printed")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        proxy_headers=False,
        log_level="warning",
        limit_concurrency=32,
        timeout_keep_alive=5,
    )


if __name__ == "__main__":
    main()
