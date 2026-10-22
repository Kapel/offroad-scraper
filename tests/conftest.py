from __future__ import annotations

from pathlib import Path

import pytest

from offroad_scraper.config import Settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"

AUTH_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        deepseek_api_key="test-key",
        output_dir=tmp_path / "data",
        sites_file=FIXTURES_DIR / "sites.yaml",
        allowed_emails=["user@example.com", "Admin@Example.com"],
        ics_auth_password=AUTH_PASSWORD,
        subscription_token="topsecret-token",
        ics_cache_max_age=60,
        published_ttl=3600,
    )


@pytest.fixture
def sample_html() -> str:
    return (FIXTURES_DIR / "sample.html").read_text(encoding="utf-8")
