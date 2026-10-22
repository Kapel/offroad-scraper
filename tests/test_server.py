from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from offroad_scraper.config import Settings
from offroad_scraper.server import create_app

ICS_BYTES = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"

PASSWORD = "correct-horse-battery-staple"


def _write_calendar(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "trips.ics").write_bytes(ICS_BYTES)


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def _auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_healthz(settings: Settings) -> None:
    with _client(settings) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_readyz_not_ready(settings: Settings) -> None:
    with _client(settings) as client:
        assert client.get("/readyz").status_code == 503


def test_readyz_ready(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        assert client.get("/readyz").status_code == 200


def test_trips_ics_requires_auth(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        response = client.get("/trips.ics")
        assert response.status_code == 401
        assert "Basic" in response.headers["www-authenticate"]


def test_trips_ics_wrong_password(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        response = client.get("/trips.ics", headers=_auth("user@example.com", "nope"))
        assert response.status_code == 401


def test_trips_ics_unknown_email(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        response = client.get("/trips.ics", headers=_auth("evil@example.com", PASSWORD))
        assert response.status_code == 401


def test_trips_ics_ok(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        response = client.get("/trips.ics", headers=_auth("user@example.com", PASSWORD))
        assert response.status_code == 200
        assert response.content == ICS_BYTES
        assert response.headers["content-type"].startswith("text/calendar")
        assert response.headers["cache-control"] == "public, max-age=60"
        assert response.headers["x-published-ttl"] == "3600"


def test_trips_ics_email_case_insensitive(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        response = client.get("/trips.ics", headers=_auth("ADMIN@example.com", PASSWORD))
        assert response.status_code == 200


def test_trips_ics_etag_304(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        first = client.get("/trips.ics", headers=_auth("user@example.com", PASSWORD))
        etag = first.headers["etag"]
        second = client.get(
            "/trips.ics",
            headers={**_auth("user@example.com", PASSWORD), "If-None-Match": etag},
        )
        assert second.status_code == 304
        assert second.content == b""


def test_trips_ics_if_modified_since_304(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        first = client.get("/trips.ics", headers=_auth("user@example.com", PASSWORD))
        last_modified = first.headers["last-modified"]
        second = client.get(
            "/trips.ics",
            headers={**_auth("user@example.com", PASSWORD), "If-Modified-Since": last_modified},
        )
        assert second.status_code == 304


def test_token_route(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        response = client.get("/ics/topsecret-token")
        assert response.status_code == 200
        assert response.content == ICS_BYTES


def test_token_route_wrong_token(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        assert client.get("/ics/wrong-token").status_code == 404


def test_token_route_disabled(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    no_token = settings.model_copy(update={"subscription_token": None})
    with _client(no_token) as client:
        assert client.get("/ics/topsecret-token").status_code == 404


def test_trips_ics_fails_closed_when_no_password(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    no_auth = settings.model_copy(update={"ics_auth_password": None})
    with _client(no_auth) as client:
        assert client.get("/trips.ics").status_code == 503


def test_security_headers(settings: Settings) -> None:
    with _client(settings) as client:
        response = client.get("/healthz")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["content-security-policy"] == "default-src 'none'"


def test_security_headers_on_error_responses(settings: Settings) -> None:
    _write_calendar(settings.output_dir)
    with _client(settings) as client:
        response = client.get("/trips.ics")
        assert response.status_code == 401
        assert response.headers["x-content-type-options"] == "nosniff"
