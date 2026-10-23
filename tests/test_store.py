from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from offroad_scraper.models import Trip
from offroad_scraper.store import TripStore


def _trip(
    *,
    destination: str = "Wadi Rum",
    start_date: str = "2026-11-02",
    end_date: str = "2026-11-09",
    price: str | None = "1290",
) -> Trip:
    return Trip.model_validate(
        {
            "destination": destination,
            "provider": "OverlandX",
            "start_date": start_date,
            "end_date": end_date,
            "price": price,
            "currency": "EUR",
            "description": "Description.",
            "url": "https://example.com/trips/1",
        }
    )


def _load(path: Path) -> list[dict[str, object]]:
    return json.loads((path / "trips.json").read_text(encoding="utf-8"))


def test_merge_creates_file(tmp_path: Path) -> None:
    TripStore(tmp_path).merge([_trip()])
    assert (tmp_path / "trips.json").exists()


def test_merge_dedupes_by_uid(tmp_path: Path) -> None:
    store = TripStore(tmp_path)
    store.merge([_trip()])
    store.merge([_trip()])
    assert len(_load(tmp_path)) == 1


def test_merge_overwrites_same_uid(tmp_path: Path) -> None:
    store = TripStore(tmp_path)
    store.merge([_trip()])
    store.merge([_trip(price="1500")])
    data = _load(tmp_path)
    assert data[0]["price"] == "1500"


def test_merge_preserves_existing_trips(tmp_path: Path) -> None:
    store = TripStore(tmp_path)
    store.merge([_trip(destination="Trip A")])
    store.merge([_trip(destination="Trip B", start_date="2026-12-02", end_date="2026-12-09")])
    data = _load(tmp_path)
    assert len(data) == 2
    assert {item["destination"] for item in data} == {"Trip A", "Trip B"}


def test_price_serialized_as_string(tmp_path: Path) -> None:
    TripStore(tmp_path).merge([_trip()])
    assert isinstance(_load(tmp_path)[0]["price"], str)


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    TripStore(tmp_path).merge([_trip()])
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".trips-")]
    assert leftovers == []


def test_all_trips_reconstructs_models(tmp_path: Path) -> None:
    store = TripStore(tmp_path)
    store.merge([_trip()])
    trips = store.all_trips()
    assert len(trips) == 1
    assert isinstance(trips[0], Trip)
    assert trips[0].price == Decimal("1290")
    assert trips[0].uid == _trip().uid


def test_prune_removes_old_trips(tmp_path: Path) -> None:
    store = TripStore(tmp_path)
    store.merge([_trip()])  # ends 2026-11-09
    store.merge([_trip(destination="Old", start_date="2026-01-01", end_date="2026-01-05")])

    removed = store.prune(date(2026, 6, 1))
    assert removed == 1
    assert [t.destination for t in store.all_trips()] == ["Wadi Rum"]


def test_merge_prefers_more_complete_trip(tmp_path: Path) -> None:
    store = TripStore(tmp_path)
    store.merge([_trip(price="1000")])
    store.merge([_trip(price=None)])
    data = _load(tmp_path)
    assert len(data) == 1
    assert data[0]["price"] == "1000"
