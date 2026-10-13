"""The process is not allowed to leave sandbox mode."""

from __future__ import annotations

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
