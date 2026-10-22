from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from offroad_scraper.config import Settings

logger = structlog.get_logger(__name__)

ICS_FILENAME = "trips.ics"
BASIC_REALM = 'Basic realm="offroad-scraper", charset="UTF-8"'

_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy", b"default-src 'none'"),
]


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware that injects security headers on every response."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                for name, value in _SECURITY_HEADERS:
                    if name not in present:
                        headers.append((name, value))
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, send_with_headers)


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title="Offroad Scraper ICS",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(SecurityHeadersMiddleware)

    ics_path = settings.output_dir / ICS_FILENAME

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        if ics_path.exists():
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "not ready"}, status_code=503)

    @app.get("/trips.ics")
    def trips_ics(request: Request) -> Response:
        auth_error = _check_basic_auth(settings, request)
        if auth_error is not None:
            return auth_error
        return _calendar_response(ics_path, settings, request)

    @app.get("/ics/{token}")
    def ics_token(token: str, request: Request) -> Response:
        if settings.subscription_token is None:
            return Response(status_code=404)
        if not hmac.compare_digest(token, settings.subscription_token.get_secret_value()):
            return Response(status_code=404)
        return _calendar_response(ics_path, settings, request)

    return app


def _check_basic_auth(settings: Settings, request: Request) -> Response | None:
    if settings.ics_auth_password is None:
        logger.error("ICS feed requested but auth is not configured")
        return _service_unavailable()

    username, password = _parse_basic_auth(request.headers.get("authorization", ""))
    client_ip = request.client.host if request.client is not None else "unknown"

    if username is None or password is None:
        logger.warning("auth failure: missing or malformed credentials", client_ip=client_ip)
        return _unauthorized()

    normalized = username.strip().lower()
    allowed = {email.strip().lower() for email in settings.allowed_emails}
    if normalized not in allowed:
        logger.warning(
            "auth failure: unknown email",
            client_ip=client_ip,
            username=_redact_username(normalized),
        )
        return _unauthorized()

    if not hmac.compare_digest(password, settings.ics_auth_password.get_secret_value()):
        logger.warning(
            "auth failure: wrong password",
            client_ip=client_ip,
            username=_redact_username(normalized),
        )
        return _unauthorized()

    return None


def _redact_username(username: str) -> str:
    return "sha256:" + hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]


def _parse_basic_auth(header: str) -> tuple[str | None, str | None]:
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic":
        return None, None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None, None
    username, sep, password = decoded.partition(":")
    if not sep:
        return None, None
    return username, password


def _unauthorized() -> Response:
    return Response(
        content="Unauthorized",
        status_code=401,
        headers={"WWW-Authenticate": BASIC_REALM},
    )


def _service_unavailable() -> Response:
    return Response(
        content="Calendar feed is not configured (set ICS_AUTH_PASSWORD or SUBSCRIPTION_TOKEN)",
        status_code=503,
    )


def _calendar_response(ics_path: Path, settings: Settings, request: Request) -> Response:
    try:
        stat = ics_path.stat()
    except OSError:
        return Response(status_code=404, content="calendar not generated yet")

    body = ics_path.read_bytes()
    etag = hashlib.sha256(body).hexdigest()
    last_modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

    if _matches_etag(request.headers.get("if-none-match"), etag):
        return Response(status_code=304)

    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since is not None:
        try:
            since = parsedate_to_datetime(if_modified_since)
        except (TypeError, ValueError, OverflowError):
            since = None
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=UTC)
            if int(last_modified.timestamp()) <= int(since.timestamp()):
                return Response(status_code=304)

    headers = {
        "Content-Type": "text/calendar; charset=utf-8",
        "Cache-Control": f"public, max-age={settings.ics_cache_max_age}",
        "X-PUBLISHED-TTL": str(settings.published_ttl),
        "ETag": f'"{etag}"',
        "Last-Modified": format_datetime(last_modified, usegmt=True),
    }
    return Response(content=body, status_code=200, headers=headers)


def _matches_etag(header: str | None, etag: str) -> bool:
    if header is None:
        return False
    for raw in header.split(","):
        candidate = raw.strip()
        if candidate == "*":
            return True
        if candidate.startswith("W/"):
            candidate = candidate[2:]
        if candidate.strip('"') == etag:
            return True
    return False
