"""Fetching a page from a user-supplied URL without opening an SSRF hole.

The scraper only fetches links on known job-board domains, but the "import job" endpoint
fetches whatever link the user typed and returns the parsed text. ``fetch_public_html``
therefore:

- only allows ``http``/``https`` URLs whose host resolves exclusively to public (global
  unicast) addresses, rejecting loopback, private, link-local (cloud metadata), CGNAT,
  multicast and reserved ranges, including IPv4-mapped IPv6 forms of them;
- connects to the address it checked (the URL host is swapped for the IP, with ``Host``
  and TLS SNI/certificate checks still using the hostname), so a DNS answer that changes
  between the check and the connect (DNS rebinding) cannot redirect the request;
- follows redirects itself, running every hop through the same checks;
- streams the body and stops at ``MAX_BYTES`` (counted after decompression).
"""

from __future__ import annotations

import ipaddress
import socket

import httpx

from app.tasks.scrape._helpers import FETCH_TIMEOUT, HEADERS

MAX_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 5


class UnsafeURLError(ValueError):
    """The URL is not an http(s) URL pointing at a public address."""


class FetchError(RuntimeError):
    """The page could not be fetched (unresolvable host, too many redirects, too large)."""


IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _is_public(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def resolve_public(host: str, port: int) -> IPAddress:
    """A public address of ``host``; raises ``UnsafeURLError`` if any address it resolves
    to is not public (a mixed answer could be steered to the private one)."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except (socket.gaierror, UnicodeError) as exc:
            raise FetchError(f"could not resolve {host}") from exc
        addresses = [ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) for info in infos]
    if not addresses:
        raise FetchError(f"could not resolve {host}")
    for ip in addresses:
        if not _is_public(ip):
            raise UnsafeURLError("the link points to a local or private network address")
    return addresses[0]


def _check_url(url: httpx.URL) -> None:
    if url.scheme not in ("http", "https") or not url.host:
        raise UnsafeURLError("link must be an http(s) URL")


def fetch_public_html(url: str, *, transport: httpx.BaseTransport | None = None) -> str:
    """Text of the page at ``url`` (see the module docstring for the guarantees)."""
    try:
        current = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise UnsafeURLError("link must be an http(s) URL") from exc
    with httpx.Client(transport=transport, follow_redirects=False, timeout=FETCH_TIMEOUT, trust_env=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _check_url(current)
            ip = resolve_public(current.host, current.port or (443 if current.scheme == "https" else 80))
            headers = {**HEADERS, "Host": current.netloc.decode("ascii")}
            extensions = {"sni_hostname": current.host} if current.scheme == "https" else {}
            pinned = current.copy_with(host=str(ip))
            with client.stream("GET", pinned, headers=headers, extensions=extensions) as resp:
                if resp.is_redirect and "location" in resp.headers:
                    current = current.join(resp.headers["location"])
                    continue
                resp.raise_for_status()
                declared = resp.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_BYTES:
                    raise FetchError("the page is too large to import")
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise FetchError("the page is too large to import")
                return body.decode(resp.encoding or "utf-8", errors="replace")
    raise FetchError("too many redirects")
