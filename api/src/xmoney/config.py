"""Runtime settings. Sandbox mode is not optional."""

from __future__ import annotations

import secrets
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from xmoney.errors import SandboxViolation
from xmoney.sandbox import assert_sandbox_daraja_host


class Settings(BaseSettings):
    """Process configuration loaded from the environment and an optional `.env` file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://xmoney:xmoney@localhost:5432/xmoney"
    sandbox_mode: bool = True
    daraja_consumer_key: str = "sandbox"
    daraja_consumer_secret: str = "sandbox"
    daraja_shortcode: str = "174379"
    daraja_passkey: str = "sandbox-passkey"
    daraja_base_url: str = "http://127.0.0.1:8000/sandbox/daraja"

    # Where Daraja sends STK callbacks. The real sandbox needs a public https URL.
    public_base_url: str = "http://127.0.0.1:8000"
    # Secret path segment of the callback URL. Hex, because Daraja rejects some words in URLs.
    # Random per process unless set; every API instance behind one URL must share it.
    stk_callback_token: str = Field(default_factory=lambda: secrets.token_hex(16), min_length=16)
    stk_query_after_seconds: int = 60
    stk_expire_after_seconds: int = 300
    stk_query_interval_seconds: int = 15

    pin_max_attempts: int = 5
    pin_lockout_minutes: int = 15
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    session_ttl_minutes: int = 720
    # Local http needs this off; anything served over https should turn it on.
    session_cookie_secure: bool = False

    # POST /v1/sandbox/journal-entries credits any account, so it is off unless a
    # developer turns it on locally. It cannot be on behind a public https URL.
    sandbox_journal_enabled: bool = False
    # PUT /sandbox/daraja/__control/behavior changes the mock's outcome for every
    # visitor. The public demo turns it off; suffix-based outcomes still work.
    daraja_mock_control_enabled: bool = True
    # The largest single top-up. The public demo lowers it.
    topup_max_cents: int = Field(default=250_000 * 100, gt=0, le=250_000 * 100)

    @model_validator(mode="after")
    def refuse_real_money(self) -> Settings:
        if self.sandbox_mode is not True:
            raise ValueError(
                "Refusing to start: X Money for Kenya is a sandbox prototype and "
                "cannot be configured to move real money."
            )
        try:
            assert_sandbox_daraja_host(self.daraja_base_url)
        except SandboxViolation as exc:
            raise ValueError(f"Refusing to start: {exc}") from exc
        if self.sandbox_journal_enabled and self.public_base_url.lower().startswith("https://"):
            raise ValueError(
                "Refusing to start: SANDBOX_JOURNAL_ENABLED is for local development and "
                "cannot be on when PUBLIC_BASE_URL is a public https URL."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
