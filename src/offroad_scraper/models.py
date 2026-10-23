from __future__ import annotations

import json
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_MAX_SHORT_TEXT = 200
_MAX_DESCRIPTION = 2000


def _sanitize_text(value: object, max_len: int) -> str:
    """Strip control characters, collapse whitespace, and cap length."""
    if not isinstance(value, str):
        raise ValueError("must be a string")
    text = _CONTROL_RE.sub(" ", value)
    text = " ".join(text.split())
    return text[:max_len]


def _coerce_decimal(value: object) -> Decimal | None:
    """Coerce a JSON-ish value to Decimal, or None. Rejects booleans."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("must be a number, not a boolean")
    if isinstance(value, (int, float, str)):
        text = str(value).strip()
        if text == "":
            return None
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"invalid number: {value!r}") from exc
    raise ValueError(f"must be a number, got {type(value).__name__}")


class Site(BaseModel):
    """A single source website listing offroad/4x4 trips.

    ``mode="single"`` (default) scrapes the configured URL directly. ``mode="list"``
    treats the URL as a listing page: candidate trip links are discovered
    deterministically and each detail page is scraped individually.
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    url: str
    note: str | None = None
    mode: Literal["single", "list"] = "single"
    feed_url: str | None = None
    max_detail_pages: int = Field(default=20, ge=1, le=100)
    exclude_paths: list[str] = Field(default_factory=list)

    @field_validator("url", "feed_url")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        if "@" in parsed.netloc:
            raise ValueError("url must not contain userinfo")
        return value


def is_recent(trip: Trip, cutoff: date) -> bool:
    """True if the trip has not ended before ``cutoff``."""
    return trip.end_date >= cutoff


class CostEstimate(BaseModel):
    """Estimated personal cost of a trip for the configured vehicle/driver."""

    model_config = ConfigDict(extra="forbid")

    distance_km: int | None = Field(default=None, ge=0)
    fuel_cost: Decimal | None = Field(default=None, ge=0)
    ferry_cost: Decimal | None = Field(default=None, ge=0)
    total_cost: Decimal | None = Field(default=None, ge=0)
    currency: str = "EUR"

    @field_validator("fuel_cost", "ferry_cost", "total_cost", mode="before")
    @classmethod
    def _coerce_money(cls, value: object) -> Decimal | None:
        return _coerce_decimal(value)

    @field_validator("distance_km", mode="before")
    @classmethod
    def _coerce_distance(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError("distance_km must be a number, not a boolean")
        if isinstance(value, int):
            return value
        if isinstance(value, (str, float, Decimal)):
            try:
                return round(Decimal(str(value)))
            except InvalidOperation as exc:
                raise ValueError(f"invalid number: {value!r}") from exc
        raise ValueError("distance_km must be a number")

    @field_validator("currency", mode="before")
    @classmethod
    def _validate_currency(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("currency must be a string")
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a 3-letter ISO-4217 code")
        return currency


class Trip(BaseModel):
    """A single extracted trip listing.

    ``description`` is a single-language text: the original English or Polish is
    preserved as-is; any other language is translated to English by the
    extractor. The offer URL is carried separately and rendered into the
    calendar description.
    """

    model_config = ConfigDict(extra="forbid")

    destination: str
    provider: str
    start_date: date
    end_date: date
    price: Decimal | None = None
    currency: str | None = None
    description: str
    url: str | None = None
    cost: CostEstimate | None = None

    @field_validator("destination", "provider")
    @classmethod
    def _sanitize_short(cls, value: str) -> str:
        text = _sanitize_text(value, _MAX_SHORT_TEXT)
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("description")
    @classmethod
    def _sanitize_description(cls, value: str) -> str:
        return _sanitize_text(value, _MAX_DESCRIPTION)

    @field_validator("price", mode="before")
    @classmethod
    def _coerce_price(cls, value: object) -> Decimal | None:
        return _coerce_decimal(value)

    @field_validator("currency", mode="before")
    @classmethod
    def _validate_currency(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("currency must be a string")
        currency = value.strip().upper()
        if currency == "":
            return None
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a 3-letter ISO-4217 code")
        return currency

    @field_validator("url")
    @classmethod
    def _validate_trip_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _sanitize_text(value, 2048)
        if value == "":
            return None
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or "@" in parsed.netloc:
            return None
        return value

    @model_validator(mode="after")
    def _check_date_order(self) -> Trip:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self

    @property
    def uid(self) -> str:
        """Stable identifier for a trip: provider + normalized destination + dates.

        The destination is normalized (lowercased, parenthetical qualifiers
        stripped) so cosmetic naming differences like "Serbia" vs "Serbia
        (Serbian Carpathians)" collapse to one event, while genuinely different
        destinations remain distinct.
        """
        key = json.dumps(
            [
                self.provider.strip().lower(),
                _normalize_destination(self.destination),
                self.start_date.isoformat(),
                self.end_date.isoformat(),
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _normalize_destination(destination: str) -> str:
    """Lowercase and strip parenthetical qualifiers for stable UID keys."""
    text = re.sub(r"\([^)]*\)", " ", destination)
    return " ".join(text.lower().split())
