from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger(__name__)

_CHUNK_SIZE = 64 * 1024
_MAX_REDIRECTS = 5


class HttpClientError(Exception):
    """Base error raised for any HTTP fetching failure."""


class ResponseTooLargeError(HttpClientError):
    """Raised when a response exceeds the configured byte limit."""

    def __init__(self, url: str, max_bytes: int) -> None:
        super().__init__(f"response from {url} exceeded the {max_bytes} byte limit")
        self.url = url
        self.max_bytes = max_bytes


def _is_public_host(host: str) -> bool:
    """Return True only if every resolved address of ``host`` is a global IP.

    Blocks loopback, private, link-local, multicast, and reserved ranges so that
    redirects cannot be used to reach internal endpoints (e.g. cloud metadata).
    """
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise HttpClientError(f"could not resolve host {host!r}") from exc
    if not infos:
        raise HttpClientError(f"could not resolve host {host!r}")
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


class HttpClient:
    """Fetches HTML with a timeout, byte cap, SSRF guard, and a stable User-Agent."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_bytes: int,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        host_check: Callable[[str], bool] | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._user_agent = user_agent
        self._transport = transport
        self._host_check = host_check or _is_public_host

    def fetch(self, url: str) -> str:
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        current = url
        with httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
            headers=headers,
            transport=self._transport,
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                try:
                    parsed = urlparse(current)
                except ValueError as exc:
                    raise HttpClientError(f"invalid URL: {current!r}") from exc
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    raise HttpClientError(f"unsupported or non-absolute URL: {current!r}")
                if not self._host_check(parsed.hostname):
                    raise HttpClientError(f"blocked non-public address for {current!r}")

                try:
                    with client.stream("GET", current) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise HttpClientError(f"redirect without location from {current}")
                            current = str(httpx.URL(current).join(location))
                            continue

                        response.raise_for_status()
                        body = self._read_limited(response, current)
                        return self._decode(body, response)
                except httpx.HTTPStatusError as exc:
                    raise HttpClientError(
                        f"HTTP {exc.response.status_code} fetching {current}"
                    ) from exc
                except httpx.HTTPError as exc:
                    raise HttpClientError(f"request failed for {current}: {exc}") from exc
        raise HttpClientError(f"too many redirects fetching {url}")

    def _read_limited(self, response: httpx.Response, url: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes(chunk_size=_CHUNK_SIZE):
            total += len(chunk)
            if total > self._max_bytes:
                raise ResponseTooLargeError(url, self._max_bytes)
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _decode(body: bytes, response: httpx.Response) -> str:
        encoding = response.encoding or "utf-8"
        try:
            return body.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            return body.decode("utf-8", errors="replace")
