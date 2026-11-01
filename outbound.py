"""Explicit outbound trust boundary, independent of ambient proxy discovery."""

from dataclasses import dataclass
import ipaddress
import os
import re
import socket
from urllib.parse import urlsplit


@dataclass(frozen=True)
class OutboundConfig:
    proxy: tuple[str, int] | None


class OutboundConfigurationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class OutboundNotSentError(ValueError):
    """Transport failed before starting the authenticated HTTP request."""


def canonical_host(value):
    if not isinstance(value, str) or not value or any(ord(c) <= 32 for c in value):
        raise OutboundConfigurationError("outbound_host_invalid")
    try:
        host = value.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise OutboundConfigurationError("outbound_host_invalid") from None
    if host.endswith("."):
        host = host[:-1]
    if not host or host.endswith(".") or len(host) > 253:
        raise OutboundConfigurationError("outbound_host_invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise OutboundConfigurationError("outbound_host_not_public_name")
    # inet_aton recognizes legacy IPv4 spelling without resolving a hostname.
    try:
        socket.inet_aton(host)
    except OSError:
        pass
    else:
        raise OutboundConfigurationError("outbound_host_not_public_name")
    labels = host.split(".")
    if (
        len(labels) < 2
        or labels[-1].isdigit()
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
    ):
        raise OutboundConfigurationError("outbound_host_invalid")
    if (
        labels[-1]
        in {"localhost", "local", "internal", "lan", "home", "localdomain", "intranet", "corp"}
        or host == "home.arpa"
        or host.endswith(".home.arpa")
    ):
        raise OutboundConfigurationError("outbound_host_not_public_name")
    return host


def proxy_config(explicit=None):
    """Unified setting wins over legacy Events setting; never use ambient proxies."""
    value = (
        explicit
        if explicit is not None
        else (
            os.environ.get("ROUNDTABLE_OUTBOUND_PROXY")
            or os.environ.get("ROUNDTABLE_EVENT_PROXY", "")
        )
    )
    if not value:
        if any(
            os.environ.get(k)
            for k in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            )
        ):
            raise OutboundConfigurationError("explicit_outbound_proxy_required")
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or any(ord(c) <= 32 for c in value)
        ):
            raise ValueError()
        port = 80 if parsed.port is None else parsed.port
        if not 1 <= port <= 65535:
            raise ValueError()
        return (parsed.hostname, port)
    except ValueError:
        raise OutboundConfigurationError("outbound_proxy_invalid") from None


def outbound_diagnostics():
    try:
        proxy = proxy_config()
        return {
            "configured": True,
            "mode": "trusted_proxy_dns" if proxy else "direct_public_ip_pinning",
            "target_public_ip_validation_required": proxy is None,
        }
    except OutboundConfigurationError as exc:
        return {"configured": False, "mode": "blocked", "reason": exc.code}
