from __future__ import annotations

import httpx
import pytest

from offroad_scraper.http_client import (
    HttpClient,
    HttpClientError,
    ResponseTooLargeError,
    _is_public_host,
)

_ALLOW_ALL = lambda host: True  # noqa: E731


def _client(max_bytes: int = 1024) -> HttpClient:
    return HttpClient(
        timeout_seconds=5.0,
        max_bytes=max_bytes,
        user_agent="test-agent",
        host_check=_ALLOW_ALL,
    )


def test_fetch_returns_html() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><body>hello</body></html>")

    client = HttpClient(
        timeout_seconds=5.0,
        max_bytes=1024,
        user_agent="t",
        transport=httpx.MockTransport(handler),
        host_check=_ALLOW_ALL,
    )
    assert "hello" in client.fetch("https://example.com/trips")


def test_fetch_enforces_max_bytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4096)

    client = HttpClient(
        timeout_seconds=5.0,
        max_bytes=1024,
        user_agent="t",
        transport=httpx.MockTransport(handler),
        host_check=_ALLOW_ALL,
    )
    with pytest.raises(ResponseTooLargeError):
        client.fetch("https://example.com/trips")


def test_fetch_rejects_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = HttpClient(
        timeout_seconds=5.0,
        max_bytes=1024,
        user_agent="t",
        transport=httpx.MockTransport(handler),
        host_check=_ALLOW_ALL,
    )
    with pytest.raises(HttpClientError):
        client.fetch("https://example.com/trips")


def test_fetch_rejects_non_http_scheme() -> None:
    with pytest.raises(HttpClientError):
        _client().fetch("file:///etc/passwd")


def test_fetch_blocks_private_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    client = HttpClient(
        timeout_seconds=5.0,
        max_bytes=1024,
        user_agent="t",
        transport=httpx.MockTransport(handler),
        host_check=lambda host: host != "internal.local",
    )
    with pytest.raises(HttpClientError, match="non-public"):
        client.fetch("https://internal.local/trips")


def test_fetch_follows_redirect_with_revalidation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "start.example":
            return httpx.Response(302, headers={"Location": "https://internal.local/trips"})
        return httpx.Response(200, content=b"ok")

    client = HttpClient(
        timeout_seconds=5.0,
        max_bytes=1024,
        user_agent="t",
        transport=httpx.MockTransport(handler),
        host_check=lambda host: host != "internal.local",
    )
    with pytest.raises(HttpClientError, match="non-public"):
        client.fetch("https://start.example/trips")


def test_is_public_host_blocks_loopback() -> None:
    assert _is_public_host("127.0.0.1") is False


def test_is_public_host_blocks_link_local() -> None:
    assert _is_public_host("169.254.169.254") is False
