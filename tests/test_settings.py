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
