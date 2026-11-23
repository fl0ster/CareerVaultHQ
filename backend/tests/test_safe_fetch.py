import socket

import httpx
import pytest

from app.tasks.scrape import safe_fetch
from app.tasks.scrape.safe_fetch import FetchError, UnsafeURLError, fetch_public_html

PUBLIC_IP = "93.184.216.34"


@pytest.fixture
def dns(monkeypatch):
    """Fake resolver: ``dns[host] = [ip, ...]``; unknown hosts fail to resolve."""
    table: dict[str, list[str]] = {}

    def getaddrinfo(host, port, *args, **kwargs):
        if host not in table:
            raise socket.gaierror("unknown host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in table[host]]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", getaddrinfo)
    return table


def transport(handler):
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    mock = httpx.MockTransport(record)
    mock.requests = requests
    return mock


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_rejects_non_public_addresses(ip):
    with pytest.raises(UnsafeURLError):
        safe_fetch.resolve_public(ip, 80)


def test_rejects_hostnames_resolving_to_private_addresses(dns):
    dns["intranet.example"] = ["10.1.2.3"]
    dns["mixed.example"] = [PUBLIC_IP, "127.0.0.1"]
    with pytest.raises(UnsafeURLError):
        fetch_public_html("http://intranet.example/", transport=transport(lambda r: httpx.Response(200)))
    with pytest.raises(UnsafeURLError):
        fetch_public_html("http://mixed.example/", transport=transport(lambda r: httpx.Response(200)))


def test_unresolvable_host_is_a_fetch_error(dns):
    with pytest.raises(FetchError):
        fetch_public_html("http://nowhere.example/")


@pytest.mark.parametrize("url", ["ftp://x.io/", "file:///etc/passwd", "/relative", "javascript:alert(1)"])
def test_rejects_non_http_urls(url):
    with pytest.raises(UnsafeURLError):
        fetch_public_html(url)


def test_connects_to_the_checked_address_with_the_original_host(dns):
    dns["jobs.example"] = [PUBLIC_IP]
    mock = transport(lambda r: httpx.Response(200, html="<h1>Job</h1>"))
    assert fetch_public_html("https://jobs.example/offer/1?x=1", transport=mock) == "<h1>Job</h1>"
    (request,) = mock.requests
    assert request.url.host == PUBLIC_IP
    assert request.url.path == "/offer/1"
    assert request.headers["host"] == "jobs.example"
    assert request.extensions["sni_hostname"] == "jobs.example"


def test_checks_every_redirect_hop(dns):
    dns["jobs.example"] = [PUBLIC_IP]
    mock = transport(lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1:6379/"}))
    with pytest.raises(UnsafeURLError):
        fetch_public_html("https://jobs.example/", transport=mock)
    assert len(mock.requests) == 1


def test_follows_public_redirects(dns):
    dns["jobs.example"] = [PUBLIC_IP]
    dns["careers.example"] = ["8.8.8.8"]

    def handler(request):
        if request.headers["host"] == "jobs.example":
            return httpx.Response(301, headers={"location": "https://careers.example/offer"})
        return httpx.Response(200, text="final")

    mock = transport(handler)
    assert fetch_public_html("https://jobs.example/", transport=mock) == "final"
    assert [r.url.host for r in mock.requests] == [PUBLIC_IP, "8.8.8.8"]


def test_stops_after_too_many_redirects(dns):
    dns["jobs.example"] = [PUBLIC_IP]
    mock = transport(lambda r: httpx.Response(302, headers={"location": "/again"}))
    with pytest.raises(FetchError, match="redirects"):
        fetch_public_html("https://jobs.example/", transport=mock)
    assert len(mock.requests) == safe_fetch.MAX_REDIRECTS + 1


def test_caps_the_body_size(dns, monkeypatch):
    monkeypatch.setattr(safe_fetch, "MAX_BYTES", 1000)
    dns["jobs.example"] = [PUBLIC_IP]

    def chunks():
        for _ in range(100):
            yield b"x" * 100

    streamed = transport(lambda r: httpx.Response(200, content=chunks()))
    with pytest.raises(FetchError, match="too large"):
        fetch_public_html("https://jobs.example/", transport=streamed)
    declared = transport(lambda r: httpx.Response(200, headers={"content-length": "5000"}, content=b"x"))
    with pytest.raises(FetchError, match="too large"):
        fetch_public_html("https://jobs.example/", transport=declared)
