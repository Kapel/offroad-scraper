from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from offroad_scraper.models import CostEstimate, Trip, is_recent


def make_trip(**overrides: object) -> Trip:
    data: dict[str, object] = {
        "destination": "Wadi Rum",
        "provider": "OverlandX",
        "start_date": "2026-11-02",
        "end_date": "2026-11-09",
        "price": "1290",
        "currency": "EUR",
        "description": "Description.",
        "url": "https://example.com/trips/1",
    }
    data.update(overrides)
    return Trip.model_validate(data)


def test_price_coerced_from_string() -> None:
    assert make_trip(price="1290").price == Decimal("1290")


def test_price_coerced_from_int() -> None:
    assert make_trip(price=1290).price == Decimal("1290")


def test_price_coerced_from_float() -> None:
    assert make_trip(price=1290.50).price == Decimal("1290.5")


def test_price_is_decimal_instance() -> None:
    assert isinstance(make_trip().price, Decimal)


def test_price_none() -> None:
    assert make_trip(price=None).price is None


def test_price_rejects_boolean() -> None:
    with pytest.raises(ValidationError):
        make_trip(price=True)


def test_currency_uppercased() -> None:
    assert make_trip(currency="usd").currency == "USD"


def test_currency_rejects_invalid() -> None:
    with pytest.raises(ValidationError):
        make_trip(currency="EURO")


def test_currency_empty_becomes_none() -> None:
    assert make_trip(currency="").currency is None


def test_end_date_before_start_date_rejected() -> None:
    with pytest.raises(ValidationError):
        make_trip(start_date="2026-11-09", end_date="2026-11-02")


def test_stable_uid() -> None:
    assert make_trip().uid == make_trip().uid
    expected = uuid.uuid5(uuid.NAMESPACE_URL, '["overlandx","2026-11-02","2026-11-09"]')
    assert make_trip().uid == str(expected)


def test_uid_ignores_destination() -> None:
    a = make_trip(destination="Serbia")
    b = make_trip(destination="Serbia (Serbian Carpathians)")
    assert a.uid == b.uid


def test_uid_changes_with_start_date() -> None:
    a = make_trip()
    b = make_trip(start_date="2026-12-02", end_date="2026-12-09")
    assert a.uid != b.uid


def test_uid_changes_with_end_date() -> None:
    a = make_trip()
    b = make_trip(end_date="2026-11-12")
    assert a.uid != b.uid


def test_url_rejects_unsafe_scheme() -> None:
    with pytest.raises(ValidationError):
        make_trip(url="javascript:alert(1)")


def test_url_rejects_userinfo() -> None:
    with pytest.raises(ValidationError):
        make_trip(url="https://user:pass@example.com/trips/1")


def test_description_strips_control_chars() -> None:
    trip = make_trip(description="Hello\x00\x1bWorld")
    assert trip.description == "Hello World"


def test_is_recent() -> None:
    trip = make_trip(end_date="2026-11-09")
    assert is_recent(trip, date(2026, 11, 9)) is True
    assert is_recent(trip, date(2026, 11, 10)) is False


def test_uid_ignores_whitespace_and_case() -> None:
    a = make_trip(provider=" OverlandX ", destination=" Wadi Rum ")
    b = make_trip(provider="overlandx", destination="wadi rum")
    assert a.uid == b.uid


def test_cost_estimate_coerces_values() -> None:
    est = CostEstimate.model_validate(
        {"distance_km": "4200", "fuel_cost": "1071.50", "ferry_cost": 700, "total_cost": 4000}
    )
    assert est.distance_km == 4200
    assert est.fuel_cost == Decimal("1071.50")
    assert est.ferry_cost == Decimal("700")
    assert est.total_cost == Decimal("4000")
    assert est.currency == "EUR"


def test_trip_with_cost() -> None:
    trip = make_trip(cost={"distance_km": 4000, "fuel_cost": 1020, "total_cost": 3000})
    assert trip.cost is not None
    assert trip.cost.distance_km == 4000
