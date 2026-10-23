from __future__ import annotations

from pathlib import Path
from typing import Annotated

import structlog
import yaml
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from offroad_scraper.models import Site

logger = structlog.get_logger(__name__)


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables (12-factor)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    log_level: str = "INFO"

    sites_file: Path = Path("/config/sites.yaml")
    output_dir: Path = Path("/data")

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_timeout_seconds: float = 120.0
    deepseek_max_tokens: int = 8000
    deepseek_temperature: float = 0.0

    extract_max_retries: int = 3
    scrape_timeout_seconds: float = 30.0
    scrape_max_bytes: int = 2_000_000
    scrape_user_agent: str = "OffroadScraper/1.0"
    retention_days: int = 90

    # Cost estimation ("total cost for you").
    home_location: str = "Warsaw, Poland"
    vehicle_description: str = "Toyota Land Cruiser 100 4.2L diesel"
    fuel_consumption_l_100km: float = 15.0
    fuel_tank_range_km: int = 500
    pln_to_eur: float = 0.23

    allowed_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    ics_auth_password: SecretStr | None = None
    subscription_token: SecretStr | None = None
    ics_cache_max_age: int = 3600
    published_ttl: int = 86400

    host: str = "0.0.0.0"  # noqa: S104  # nosec B104 - bind-all for in-container serving
    port: int = 8080

    @field_validator("allowed_emails", mode="before")
    @classmethod
    def _split_allowed_emails(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [email.strip() for email in value.split(",") if email.strip()]
        if isinstance(value, list):
            return [str(email) for email in value]
        return []

    @field_validator("ics_auth_password", "subscription_token", mode="before")
    @classmethod
    def _empty_secret_to_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, SecretStr):
            return None if value.get_secret_value().strip() == "" else value
        if isinstance(value, str):
            return None if value.strip() == "" else value
        return value

    @field_validator("extract_max_retries", mode="after")
    @classmethod
    def _non_negative_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("EXTRACT_MAX_RETRIES must be >= 0")
        return value

    @field_validator("retention_days", mode="after")
    @classmethod
    def _non_negative_retention(cls, value: int) -> int:
        if value < 0:
            raise ValueError("RETENTION_DAYS must be >= 0")
        return value

    @field_validator("port", mode="after")
    @classmethod
    def _port_range(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
        return value

    @field_validator("scrape_max_bytes", "deepseek_max_tokens", mode="after")
    @classmethod
    def _positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be positive")
        return value

    @field_validator("scrape_timeout_seconds", "deepseek_timeout_seconds", mode="after")
    @classmethod
    def _positive_float(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("value must be positive")
        return value

    @field_validator("fuel_consumption_l_100km", "pln_to_eur", mode="after")
    @classmethod
    def _positive_cost_float(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("value must be positive")
        return value

    @field_validator("fuel_tank_range_km", mode="after")
    @classmethod
    def _positive_tank_range(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("fuel_tank_range_km must be positive")
        return value


def load_sites(path: Path) -> list[Site]:
    """Load and validate the sites YAML file, skipping invalid entries."""
    if not path.exists():
        logger.error("sites file not found", path=str(path))
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.error("failed to parse sites file", path=str(path), error=str(exc))
        return []
    if not isinstance(data, dict):
        logger.error("sites file must be a YAML mapping", path=str(path))
        return []
    raw_sites = data.get("sites")
    if not isinstance(raw_sites, list):
        logger.error("sites file is missing a 'sites' list", path=str(path))
        return []

    sites: list[Site] = []
    for raw in raw_sites:
        try:
            sites.append(Site.model_validate(raw))
        except ValidationError as exc:
            logger.warning("skipping invalid site entry", error=str(exc))
    return sites
