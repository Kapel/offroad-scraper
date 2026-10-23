from __future__ import annotations

import contextlib
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from icalendar import Calendar, Event, vDate, vText

from offroad_scraper.models import CostEstimate, Trip

PRODID = "-//OffroadScraper//Trips//EN"
CALENDAR_NAME = "Offroad 4x4 Trips"
ICS_FILENAME = "trips.ics"


def build_calendar(trips: list[Trip], calname: str = CALENDAR_NAME) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("calname", calname)
    for trip in trips:
        calendar.add_component(_build_event(trip))
    return bytes(calendar.to_ical())


def write_calendar_atomic(
    output_dir: Path, trips: list[Trip], calname: str = CALENDAR_NAME
) -> Path:
    """Build the ICS and atomically replace OUTPUT_DIR/trips.ics."""
    data = build_calendar(trips, calname)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / ICS_FILENAME

    fd, tmp_name = tempfile.mkstemp(dir=str(output_dir), prefix=".trips-", suffix=".ics.tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return target


def _build_event(trip: Trip) -> Event:
    event = Event()
    event.add("uid", trip.uid)
    event.add("dtstamp", datetime.now(UTC))
    event.add("dtstart", vDate(trip.start_date))
    event.add("dtend", vDate(trip.end_date + timedelta(days=1)))
    event.add("summary", vText(_summary(trip)))
    event.add("description", vText(_description(trip)))
    return event


def _summary(trip: Trip) -> str:
    return f"{trip.destination} — {trip.provider}"


def _description(trip: Trip) -> str:
    lines = [f"Dates: {trip.start_date.isoformat()} to {trip.end_date.isoformat()}"]
    if trip.price is not None:
        suffix = f" {trip.currency}" if trip.currency else ""
        lines.append(f"Price: {trip.price}{suffix}")
    if trip.cost is not None:
        lines.append(_cost_line(trip.cost))
    if trip.url:
        lines.append(f"Link: {trip.url}")
    lines.append("")
    lines.append(trip.description)
    return "\n".join(lines)


def _cost_line(cost: CostEstimate) -> str:
    parts: list[str] = []
    if cost.distance_km is not None:
        parts.append(f"~{cost.distance_km} km")
    if cost.fuel_cost is not None:
        parts.append(f"fuel {cost.fuel_cost} {cost.currency}")
    if cost.ferry_cost is not None:
        parts.append(f"ferry {cost.ferry_cost} {cost.currency}")
    total = cost.total_cost
    if total is not None:
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Total cost for you: {total} {cost.currency}{detail}"
    return "Total cost for you: n/a"
