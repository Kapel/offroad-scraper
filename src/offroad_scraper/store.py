from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

import structlog
from pydantic import ValidationError

from offroad_scraper.models import Trip

logger = structlog.get_logger(__name__)

TRIPS_FILENAME = "trips.json"
SIGNATURE_FILENAME = ".trips.sig"


def _completeness(item: dict[str, object]) -> int:
    """Score a serialized trip by how much data it carries (higher = richer)."""
    score = 0
    if item.get("price") is not None:
        score += 2
    if item.get("url"):
        score += 1
    if item.get("description"):
        score += 1
    return score


class StoreError(Exception):
    """Raised when the persisted store cannot be read or written safely."""


class TripStore:
    """Persists trips as a JSON array, keyed by stable UID, with atomic writes."""

    def __init__(self, output_dir: Path) -> None:
        self._dir = output_dir
        self._path = output_dir / TRIPS_FILENAME

    def load(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"failed to read {self._path}: {exc}") from exc
        if not isinstance(raw, list):
            raise StoreError(f"{self._path} is not a JSON array")

        result: dict[str, dict[str, object]] = {}
        for item in raw:
            if isinstance(item, dict):
                uid = item.get("uid")
                if isinstance(uid, str):
                    result[uid] = item
        return result

    def merge(self, trips: list[Trip]) -> int:
        """Merge trips into the store by UID; return the number of newly added trips."""
        existing = self.load()
        added = 0
        for trip in trips:
            uid = trip.uid
            serialized = self._serialize(trip)
            if uid in existing:
                if _completeness(serialized) >= _completeness(existing[uid]):
                    existing[uid] = serialized
            else:
                added += 1
                existing[uid] = serialized
        self._write_atomic(list(existing.values()))
        return added

    def prune(self, cutoff: date) -> int:
        """Remove trips whose end date is before ``cutoff``; return the count removed."""
        trips = self.all_trips()
        kept = [trip for trip in trips if trip.end_date >= cutoff]
        removed = len(trips) - len(kept)
        if removed:
            self._write_atomic([self._serialize(trip) for trip in kept])
            logger.info("pruned old trips", removed=removed, cutoff=cutoff.isoformat())
        return removed

    def all_trips(self) -> list[Trip]:
        trips: list[Trip] = []
        for item in self.load().values():
            data = dict(item)
            data.pop("uid", None)
            try:
                trips.append(Trip.model_validate(data))
            except ValidationError as exc:
                logger.warning("skipping invalid stored trip", uid=item.get("uid"), error=str(exc))
        return trips

    def _serialize(self, trip: Trip) -> dict[str, object]:
        cost = trip.cost
        return {
            "uid": trip.uid,
            "destination": trip.destination,
            "provider": trip.provider,
            "start_date": trip.start_date.isoformat(),
            "end_date": trip.end_date.isoformat(),
            "price": str(trip.price) if trip.price is not None else None,
            "currency": trip.currency,
            "description": trip.description,
            "url": trip.url,
            "cost": None
            if cost is None
            else {
                "distance_km": cost.distance_km,
                "fuel_cost": str(cost.fuel_cost) if cost.fuel_cost is not None else None,
                "ferry_cost": str(cost.ferry_cost) if cost.ferry_cost is not None else None,
                "total_cost": str(cost.total_cost) if cost.total_cost is not None else None,
                "currency": cost.currency,
            },
        }

    def content_signature(self) -> str:
        """Return a stable hash of the persisted trips (empty string if absent).

        Used to detect whether the calendar needs to be rebuilt. An unreadable
        file yields "" (treated as "changed") so the calendar is rebuilt rather
        than silently skipped.
        """
        if not self._path.exists():
            return ""
        try:
            return hashlib.sha256(self._path.read_bytes()).hexdigest()
        except OSError as exc:
            logger.error("failed to read trips.json for signature", error=str(exc))
            return ""

    def load_signature(self) -> str:
        sig_path = self._dir / SIGNATURE_FILENAME
        if not sig_path.exists():
            return ""
        try:
            return sig_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def save_signature(self, signature: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        sig_path = self._dir / SIGNATURE_FILENAME
        fd, tmp_name = tempfile.mkstemp(dir=str(self._dir), prefix=".sig-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(signature)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, sig_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    def _write_atomic(self, trips: list[dict[str, object]]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(trips, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, tmp_name = tempfile.mkstemp(dir=str(self._dir), prefix=".trips-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
