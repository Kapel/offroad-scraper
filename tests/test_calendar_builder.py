from __future__ import annotations

from datetime import date
from pathlib import Path

from icalendar import Calendar

from offroad_scraper.calendar_builder import build_calendar, write_calendar_atomic
from offroad_scraper.models import Trip


def _trip() -> Trip:
    return Trip.model_validate(
        {
            "destination": "Wadi Rum",
            "provider": "OverlandX",
            "start_date": "2026-11-02",
            "end_date": "2026-11-09",
            "price": "1290",
            "currency": "EUR",
            "description": "Sleeping under the stars.",
            "url": "https://example.com/trips/1",
        }
    )


def _event(data: bytes) -> object:
    calendar = Calendar.from_ical(data)
    return next(iter(calendar.walk("VEVENT")))


def test_calendar_parses() -> None:
    calendar = Calendar.from_ical(build_calendar([_trip()]))
    assert str(calendar["prodid"]) == "-//OffroadScraper//Trips//EN"
    assert str(calendar["version"]) == "2.0"
    assert len(list(calendar.walk("VEVENT"))) == 1


def test_dtend_is_exclusive() -> None:
    event = _event(build_calendar([_trip()]))
    assert event["dtstart"].dt == date(2026, 11, 2)
    assert event["dtend"].dt == date(2026, 11, 10)


def test_summary_format() -> None:
    event = _event(build_calendar([_trip()]))
    assert str(event["summary"]) == "Wadi Rum — OverlandX"


def test_description_contains_fields() -> None:
    event = _event(build_calendar([_trip()]))
    description = str(event["description"])
    assert "2026-11-02" in description
    assert "1290" in description
    assert "EUR" in description
    assert "https://example.com/trips/1" in description
    assert "Sleeping under the stars." in description


def test_uid_matches_trip() -> None:
    event = _event(build_calendar([_trip()]))
    assert str(event["uid"]) == _trip().uid


def test_description_escaping_roundtrip() -> None:
    trip = _trip().model_copy(
        update={"description": "Line one\nLine two, with comma; and semicolon"}
    )
    event = _event(build_calendar([trip]))
    description = str(event["description"])
    assert "Line one" in description
    assert "Line two, with comma; and semicolon" in description


def test_multiple_events() -> None:
    a = _trip()
    b = _trip().model_copy(update={"start_date": date(2026, 12, 1), "end_date": date(2026, 12, 5)})
    calendar = Calendar.from_ical(build_calendar([a, b]))
    assert len(list(calendar.walk("VEVENT"))) == 2


def test_write_calendar_atomic(tmp_path: Path) -> None:
    path = write_calendar_atomic(tmp_path, [_trip()])
    assert path == tmp_path / "trips.ics"
    assert path.exists()
    assert Calendar.from_ical(path.read_bytes())
