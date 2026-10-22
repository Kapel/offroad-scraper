from __future__ import annotations

import json
from datetime import date

import httpx
import openai
import pytest

from offroad_scraper import extractor as extractor_module
from offroad_scraper.config import Settings
from offroad_scraper.extractor import Extractor, truncate_html

VALID_TRIPS_JSON = json.dumps(
    {
        "trips": [
            {
                "destination": "Wadi Rum",
                "provider": "OverlandX",
                "start_date": "2026-11-02",
                "end_date": "2026-11-09",
                "price": 1290,
                "currency": "EUR",
                "description": "A description in English.",
                "url": "https://example.com/trips/1",
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
    def __init__(self, responses: list[str | BaseException]) -> None:
        self._responses = responses
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _FakeResponse(item)


class _FakeChat:
    def __init__(self, responses: list[str | BaseException]) -> None:
        self.completions = _FakeCompletions(responses)


class _FakeClient:
    def __init__(self, responses: list[str | BaseException]) -> None:
        self.chat = _FakeChat(responses)


@pytest.fixture
def make_extractor(monkeypatch: pytest.MonkeyPatch):
    def _factory(
        settings: Settings, responses: list[str | BaseException]
    ) -> tuple[Extractor, _FakeClient]:
        fake = _FakeClient(responses)
        monkeypatch.setattr(extractor_module, "OpenAI", lambda **_: fake)
        return Extractor(settings), fake

    return _factory


def _status_error(status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(status, request=request)
    return openai.APIStatusError(f"error {status}", response=response, body=None)


def test_extract_parses_valid_json(settings: Settings, make_extractor) -> None:
    extractor, fake = make_extractor(settings, [VALID_TRIPS_JSON])
    trips = extractor.extract("OverlandX", "<html><body>trips</body></html>")

    assert len(trips) == 1
    assert trips[0].destination == "Wadi Rum"
    assert str(trips[0].price) == "1290"
    assert trips[0].currency == "EUR"
    assert trips[0].start_date == date(2026, 11, 2)

    kwargs = fake.chat.completions.calls[0]
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0.0
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert kwargs["model"] == settings.deepseek_model
    assert "json" in kwargs["messages"][0]["content"]


def test_extract_retries_on_invalid_json(settings: Settings, make_extractor) -> None:
    extractor, fake = make_extractor(settings, ["not json at all", VALID_TRIPS_JSON])
    trips = extractor.extract("OverlandX", "<html></html>")

    assert len(trips) == 1
    assert len(fake.chat.completions.calls) == 2
    second_messages = fake.chat.completions.calls[1]["messages"]
    assert len(second_messages) == 3
    assert "rejected" in second_messages[2]["content"]


def test_extract_skips_invalid_item_and_keeps_valid(settings: Settings, make_extractor) -> None:
    mixed = json.dumps(
        {
            "trips": [
                {
                    "destination": "Bad",
                    "provider": "Y",
                    "start_date": "2026-11-02",
                    "end_date": "2026-11-09",
                    "currency": "EURO",
                    "description": "d",
                },
                json.loads(VALID_TRIPS_JSON)["trips"][0],
            ]
        }
    )
    extractor, fake = make_extractor(settings, [mixed])
    trips = extractor.extract("OverlandX", "<html></html>")

    assert len(trips) == 1
    assert trips[0].destination == "Wadi Rum"
    assert len(fake.chat.completions.calls) == 1


def test_extract_retries_on_malformed_envelope(settings: Settings, make_extractor) -> None:
    extractor, fake = make_extractor(settings, [json.dumps({"foo": []}), VALID_TRIPS_JSON])
    trips = extractor.extract("OverlandX", "<html></html>")

    assert len(trips) == 1
    assert len(fake.chat.completions.calls) == 2


def test_extract_returns_empty_after_retries(settings: Settings, make_extractor) -> None:
    extractor, fake = make_extractor(settings, ["bad"] * 4)
    trips = extractor.extract("OverlandX", "<html></html>")

    assert trips == []
    assert len(fake.chat.completions.calls) == 4


def test_extract_retries_on_api_error(settings: Settings, make_extractor) -> None:
    extractor, fake = make_extractor(settings, [_status_error(500), VALID_TRIPS_JSON])
    trips = extractor.extract("OverlandX", "<html></html>")

    assert len(trips) == 1
    assert len(fake.chat.completions.calls) == 2


def test_extract_fatal_api_error_propagates(settings: Settings, make_extractor) -> None:
    extractor, _ = make_extractor(settings, [_status_error(401)])
    with pytest.raises(openai.APIStatusError):
        extractor.extract("OverlandX", "<html></html>")


def test_extract_returns_empty_on_empty_result(settings: Settings, make_extractor) -> None:
    extractor, fake = make_extractor(settings, [json.dumps({"trips": []})] * 4)
    trips = extractor.extract("OverlandX", "<html></html>")

    assert trips == []
    assert len(fake.chat.completions.calls) == 1


def test_truncate_html_strips_scripts_and_styles() -> None:
    html = "<html><script>evil()</script><style>h1{}</style><h1>Hello</h1></html>"
    result = truncate_html(html)
    assert "Hello" in result
    assert "evil()" not in result
    assert "h1{}" not in result


def test_truncate_html_limits_length() -> None:
    html = "<p>" + ("a" * 20_000) + "</p>"
    assert len(truncate_html(html)) <= 15_000
