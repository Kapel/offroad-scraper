from __future__ import annotations

import json
from decimal import Decimal

import pytest

from offroad_scraper import cost_estimator as ce
from offroad_scraper.config import Settings
from offroad_scraper.cost_estimator import CostEstimator
from offroad_scraper.models import Trip

ESTIMATES_JSON = json.dumps(
    {
        "estimates": [
            {
                "index": 0,
                "distance_km": 4200,
                "fuel_cost": 1071,
                "ferry_cost": 700,
                "total_cost": 4000,
            }
        ]
    }
)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)
        self.finish_reason = "stop"


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(self._content)


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})()


def _trip(**overrides: object) -> Trip:
    data: dict[str, object] = {
        "destination": "Bosnia",
        "provider": "Further Adventures",
        "start_date": "2027-05-18",
        "end_date": "2027-05-28",
        "price": "1290",
        "currency": "EUR",
        "description": "A trip.",
    }
    data.update(overrides)
    return Trip.model_validate(data)


@pytest.fixture
def make_estimator(monkeypatch: pytest.MonkeyPatch, settings: Settings):
    def _factory(content: str) -> tuple[CostEstimator, _FakeClient]:
        fake = _FakeClient(content)
        monkeypatch.setattr(ce, "OpenAI", lambda **_: fake)
        return CostEstimator(settings), fake

    return _factory


def test_estimate_attaches_cost(settings: Settings, make_estimator) -> None:
    estimator, fake = make_estimator(ESTIMATES_JSON)
    trips = [_trip()]
    result = estimator.estimate(trips)

    assert result[0].cost is not None
    assert result[0].cost.distance_km == 4200
    assert result[0].cost.fuel_cost == Decimal("1071")
    assert result[0].cost.ferry_cost == Decimal("700")
    assert result[0].cost.total_cost == Decimal("4000")

    # Prompt carries the vehicle/home config.
    system = fake.chat.completions.calls[0]["messages"][0]["content"]
    assert "Land Cruiser 100" in system
    assert "Warsaw" in system


def test_estimate_returns_unchanged_on_empty(settings: Settings, make_estimator) -> None:
    estimator, _ = make_estimator(ESTIMATES_JSON)
    assert estimator.estimate([]) == []


def test_estimate_swallows_bad_output(settings: Settings, make_estimator) -> None:
    estimator, _ = make_estimator("not json")
    trips = [_trip()]
    result = estimator.estimate(trips)
    assert result[0].cost is None
