"""Outbound request safety (SSRF) for every URL a user can make the server fetch.

Two places take a URL from the user: dossier URLs (characterisation.py) and custom AI endpoints (ai.py).
Both go through this module, which

- refuses anything but http(s), embedded credentials and well-known internal names;
- resolves the host and refuses loopback, link-local (cloud metadata), private, carrier-grade NAT, reserved
  and multicast addresses, including IPv4 addresses hidden inside IPv6 ones (IPv4-mapped, 6to4, Teredo, NAT64);
- connects to the address that was checked. Without this "pinning" a hostile DNS server can answer the check
  with a public address and the connection with an internal one (DNS rebinding).

When the deployment reaches the internet through an outbound proxy (HTTPS_PROXY and friends), the proxy does
the name resolution, so pinning is not possible; the checks above still run on whatever resolves locally.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Iterator, Optional
from urllib.parse import urlsplit

import httpx

BLOCKED_HOSTNAMES = ("localhost", "metadata", "metadata.google.internal", "instance-data")
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa")
_NAT64_NETS = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


class BlockedURL(ValueError):
    """The URL points somewhere the server must not connect to. The message is safe to show the user."""


def _embedded(addr: ipaddress._BaseAddress) -> Iterator[ipaddress._BaseAddress]:
    """The address itself and every IPv4 address it can smuggle."""
    yield addr
    if addr.version != 6:
        return
    if addr.ipv4_mapped:
        yield addr.ipv4_mapped
    if addr.sixtofour:
        yield addr.sixtofour
    if addr.teredo:
        yield from addr.teredo
    if any(addr in net for net in _NAT64_NETS) or (int(addr) >> 32) == 0:  # NAT64, and ::a.b.c.d (IPv4-compatible)
        yield ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)


def address_block_reason(ip: str, allow_private: bool = False) -> str:
    """'' when the server may connect to this address, else why not."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])  # drop an IPv6 zone id
    except ValueError:
        return "not an IP address"
    for a in _embedded(addr):
        if (a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified
                or getattr(a, "is_site_local", False)):
            return "a blocked address range"
        if not a.is_global and not allow_private:
            return "a private address"
    return ""


def uses_env_proxy() -> bool:
    return any(os.getenv(k) or os.getenv(k.lower()) for k in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"))


def _allowed_ports() -> Optional[set[int]]:
    raw = os.getenv("KEVIDENCE_FETCH_PORTS", "").strip()
    if not raw:
        return None
    return {int(p) for p in raw.split(",") if p.strip().isdigit()}


def resolve_checked(host: str, port: int, allow_private: bool = False) -> list[str]:
    """Addresses of `host`, all of them allowed. Raises BlockedURL otherwise."""
    host = (host or "").strip().rstrip(".").lower()
    if not host:
        raise BlockedURL("the URL has no host")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        raise BlockedURL("the host is not permitted")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        reason = address_block_reason(str(literal), allow_private)
        if reason:
            raise BlockedURL(f"the host is {reason}")
        return [str(literal)]
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        if uses_env_proxy():
            return []  # only the outbound proxy can resolve it; the proxy is the egress control
        raise BlockedURL("the host does not resolve from this server") from None
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise BlockedURL("the host does not resolve from this server")
    for ip in addresses:
        reason = address_block_reason(ip, allow_private)
        if reason:
            raise BlockedURL(f"the host resolves to {reason}")
    return addresses


def check_url(url: str, *, allow_private: bool = False, allow_http: bool = True) -> tuple[str, list[str]]:
    """Validate a user-supplied URL. Returns (normalised URL, checked addresses). Raises BlockedURL."""
    try:
        parts = urlsplit((url or "").strip())
        port = parts.port
    except ValueError:
        raise BlockedURL("not a valid URL") from None
    if parts.scheme not in ("http", "https"):
        raise BlockedURL("only http(s) URLs are accepted")
    if parts.scheme == "http" and not allow_http:
        raise BlockedURL("plain http is not permitted")
    if parts.username or parts.password:
        raise BlockedURL("credentials must not be embedded in the URL")
    if not parts.hostname:
        raise BlockedURL("the URL has no host")
    port = port or (443 if parts.scheme == "https" else 80)
    allowed = _allowed_ports()
    if allowed is not None and port not in allowed:
        raise BlockedURL(f"port {port} is not permitted")
    return parts.geturl(), resolve_checked(parts.hostname, port, allow_private)


class PinnedTransport(httpx.BaseTransport):
    """Connects only to an address that passed the checks, whatever DNS says a moment later.

    The request goes to the checked IP; the Host header (set by httpx from the original URL) and the TLS
    server name (SNI and certificate check) stay those of the hostname."""

    def __init__(self, allow_private: bool = False, **kwargs):
        self.allow_private = allow_private
        self._inner = httpx.HTTPTransport(**kwargs)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        try:
            addresses = resolve_checked(host, port, self.allow_private)
        except BlockedURL as exc:
            raise httpx.ConnectError(f"Refused: {exc}", request=request) from None
        if not addresses:
            raise httpx.ConnectError("Refused: the host does not resolve from this server", request=request)
        ip = addresses[0]
        if ip != host.strip("[]"):
            request.url = request.url.copy_with(host=ip)
            request.extensions = {**request.extensions, "sni_hostname": host}
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def client(*, allow_private: bool = False, **kwargs) -> httpx.Client:
    """An httpx client for user-supplied URLs. Redirects are never followed automatically: the caller
    re-validates each hop."""
    kwargs["follow_redirects"] = False
    if uses_env_proxy():
        return httpx.Client(**kwargs)
    return httpx.Client(transport=PinnedTransport(allow_private=allow_private), **kwargs)
