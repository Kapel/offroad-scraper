from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from offroad_scraper.config import Settings, load_sites

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_allowed_emails_split_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_EMAILS", "a@x.com, b@y.com")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    assert Settings().allowed_emails == ["a@x.com", "b@y.com"]


def test_deepseek_api_key_optional(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert Settings().deepseek_api_key is None


def test_empty_password_normalized_to_none(monkeypatch) -> None:
    monkeypatch.setenv("ICS_AUTH_PASSWORD", "")
    monkeypatch.setenv("SUBSCRIPTION_TOKEN", "   ")
    settings = Settings()
    assert settings.ics_auth_password is None
    assert settings.subscription_token is None


def test_port_range_validated(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "99999")
    with pytest.raises(ValidationError):
        Settings()


def test_load_sites_from_fixture() -> None:
    sites = load_sites(FIXTURES_DIR / "sites.yaml")
    assert len(sites) == 2
    assert sites[0].name == "OverlandX"
    assert sites[0].url == "https://example.com/trips"
    assert sites[0].note == "offroad 4x4 trips"


def test_load_sites_missing_file() -> None:
    assert load_sites(Path("/nonexistent/sites.yaml")) == []


def test_load_sites_skips_invalid_entries(tmp_path: Path) -> None:
    path = tmp_path / "sites.yaml"
    path.write_text(
        "sites:\n  - name: Good\n    url: https://example.com\n  - name: Bad\n    url: not-a-url\n",
        encoding="utf-8",
    )
    sites = load_sites(path)
    assert len(sites) == 1
    assert sites[0].name == "Good"


def test_load_sites_list_mode_defaults_and_fields(tmp_path: Path) -> None:
    path = tmp_path / "sites.yaml"
    path.write_text(
        "sites:\n"
        "  - name: List\n"
        "    url: https://example.com/trips\n"
        "    mode: list\n"
        "    max_detail_pages: 5\n"
        "    exclude_paths: ['/reserve', '/contact']\n",
        encoding="utf-8",
    )
    sites = load_sites(path)
    assert sites[0].mode == "list"
    assert sites[0].max_detail_pages == 5
    assert sites[0].exclude_paths == ["/reserve", "/contact"]


def test_site_defaults_to_single_mode(tmp_path: Path) -> None:
    path = tmp_path / "sites.yaml"
    path.write_text("sites:\n  - name: X\n    url: https://example.com\n", encoding="utf-8")
    sites = load_sites(path)
    assert sites[0].mode == "single"
    assert sites[0].max_detail_pages == 20
    assert sites[0].exclude_paths == []
