from __future__ import annotations

import json
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

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


class Site(BaseModel):
    """A single source website listing offroad/4x4 trips."""

    model_config = ConfigDict(extra="ignore")

    name: str
    url: str
    note: str | None = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        if "@" in parsed.netloc:
            raise ValueError("url must not contain userinfo")
        return value


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
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        if isinstance(value, bool):
            raise ValueError("price must be a number, not a boolean")
        if isinstance(value, (int, float, str)):
            text = str(value).strip()
            if text == "":
                return None
            try:
                return Decimal(text)
            except InvalidOperation as exc:
                raise ValueError(f"invalid price value: {value!r}") from exc
        raise ValueError(f"price must be a number, got {type(value).__name__}")

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
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        if "@" in parsed.netloc:
            raise ValueError("url must not contain userinfo")
        return value

    @model_validator(mode="after")
    def _check_date_order(self) -> Trip:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self

    @property
    def uid(self) -> str:
        """Stable identifier, identical for the same logical trip across runs.

        The key is a canonical JSON array (not a delimited string) so that
        free-text values cannot collide by embedding the delimiter.
        """
        key = json.dumps(
            [
                self.provider.strip().lower(),
                self.destination.strip().lower(),
                self.start_date.isoformat(),
                self.end_date.isoformat(),
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, key))
