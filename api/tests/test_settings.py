"""The process is not allowed to leave sandbox mode."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from xmoney.config import Settings, get_settings


def test_refuses_to_disable_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_MODE", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError, match="cannot be configured to move real money"):
            Settings()
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "base_url", ["https://api.safaricom.co.ke", "https://api.safaricom.co.ke./mpesa"]
)
def test_refuses_production_daraja_url_at_startup(
    monkeypatch: pytest.MonkeyPatch, base_url: str
) -> None:
    monkeypatch.setenv("DARAJA_BASE_URL", base_url)
    with pytest.raises(ValidationError, match="Refusing to start"):
        Settings()


def test_accepts_the_public_daraja_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARAJA_BASE_URL", "https://sandbox.safaricom.co.ke")
    assert Settings().daraja_base_url == "https://sandbox.safaricom.co.ke"


def test_database_url_is_built_from_rds_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_HOST", "xmoney.abc123.eu-west-1.rds.amazonaws.com")
    monkeypatch.setenv("DB_USERNAME", "xmoney")
    monkeypatch.setenv("DB_PASSWORD", "p@ss:w/rd?#%")
    url = urlparse(Settings().sqlalchemy_url)
    assert url.scheme == "postgresql+psycopg"
    assert url.hostname == "xmoney.abc123.eu-west-1.rds.amazonaws.com"
    assert url.port == 5432 and url.path == "/xmoney"
    assert parse_qs(url.query) == {"sslmode": ["require"]}
    assert "p@ss" not in url.netloc


def test_db_host_needs_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_HOST", "db.internal")
    with pytest.raises(ValidationError, match="DB_USERNAME and DB_PASSWORD"):
        Settings()


def test_database_url_is_used_as_is_without_db_host() -> None:
    assert Settings(database_url="postgresql+psycopg://a:b@h/d").sqlalchemy_url == (
        "postgresql+psycopg://a:b@h/d"
    )
