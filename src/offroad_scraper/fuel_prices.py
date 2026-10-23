from __future__ import annotations

import html as html_lib
import io
import json
import re
import time
from pathlib import Path

import httpx
import openpyxl
import structlog
from openpyxl.utils.exceptions import InvalidFileException

logger = structlog.get_logger(__name__)

BULLETIN_PAGE_URL = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"
_DOWNLOAD_RE = re.compile(r'href="(/document/download/[^"]*filename=[^"]*[Tt]axes[^"]*\.xlsx)"')


class FuelPriceProvider:
    """Fetches weekly EU diesel prices (EUR/litre) from the Weekly Oil Bulletin.

    Results are cached to a JSON file and refreshed at most every ``refresh_days``.
    """

    def __init__(self, cache_path: Path, *, refresh_days: int = 7, timeout: float = 30.0) -> None:
        self._cache_path = cache_path
        self._refresh_days = refresh_days
        self._timeout = timeout

    def prices(self) -> dict[str, float]:
        """Return a country -> EUR/litre diesel map (empty on failure)."""
        cached = self._load_cache()
        if cached is not None:
            return cached
        fresh = self._fetch()
        if fresh:
            self._save_cache(fresh)
            return fresh
        logger.warning("could not fetch EU fuel prices; using model knowledge only")
        return {}

    def _load_cache(self) -> dict[str, float] | None:
        if not self._cache_path.exists():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if time.time() - float(data.get("fetched_at", 0)) > self._refresh_days * 86400:
            return None
        prices = data.get("prices")
        return prices if isinstance(prices, dict) else None

    def _save_cache(self, prices: dict[str, float]) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fetched_at": time.time(), "prices": prices}), encoding="utf-8")
        tmp.replace(self._cache_path)

    def _fetch(self) -> dict[str, float]:
        page = self._get_text(BULLETIN_PAGE_URL)
        if page is None:
            return {}
        match = _DOWNLOAD_RE.search(page)
        if match is None:
            logger.warning("no oil bulletin download link found on the page")
            return {}
        url = "https://energy.ec.europa.eu" + html_lib.unescape(match.group(1))
        raw = self._get_bytes(url)
        if raw is None:
            return {}
        return self._parse(raw)

    def _get_text(self, url: str) -> str | None:
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as exc:
            logger.error("failed to fetch oil bulletin page", url=url, error=str(exc))
            return None

    def _get_bytes(self, url: str) -> bytes | None:
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.content
        except httpx.HTTPError as exc:
            logger.error("failed to download oil bulletin xlsx", url=url, error=str(exc))
            return None

    @staticmethod
    def _parse(raw: bytes) -> dict[str, float]:
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        except (InvalidFileException, ValueError, KeyError, OSError) as exc:
            logger.error("failed to parse oil bulletin xlsx", error=str(exc))
            return {}
        sheet = workbook.active
        prices: dict[str, float] = {}
        for row in sheet.iter_rows(values_only=True):
            if not row or row[0] is None:
                continue
            country = str(row[0]).strip()
            diesel = row[2]
            if (
                not country
                or "(" in country
                or country.startswith("CE/")
                or country in {"Moyenne pondérée", "Weighted average", "Gewichteter Durchschnitt"}
            ):
                continue
            if isinstance(diesel, (int, float)) and diesel > 0:
                # The bulletin reports EUR per 1000 litres.
                prices[country] = round(float(diesel) / 1000.0, 2)
        return prices
