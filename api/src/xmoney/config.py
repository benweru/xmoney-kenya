"""Runtime settings. Sandbox mode is not optional."""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from xmoney.errors import InvalidPhone, SandboxViolation
from xmoney.identity.validators import normalize_phone
from xmoney.sandbox import assert_sandbox_daraja_host

RailName = Literal["mock", "sandbox"]


class Settings(BaseSettings):
    """Process configuration loaded from the environment and an optional `.env` file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://xmoney:xmoney@localhost:5432/xmoney"
    # On AWS the URL is assembled from these, so the RDS-managed password never sits
    # in a plain environment variable. DATABASE_URL is ignored when DB_HOST is set.
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "xmoney"
    db_username: str | None = None
    db_password: str | None = None
    db_sslmode: str = "require"
    sandbox_mode: bool = True

    # Top-up rails a visitor can choose, default first. `mock` is the Daraja mock this
    # API serves; `sandbox` is Safaricom's Daraja sandbox with the DARAJA_* keys below.
    payment_rails: list[RailName] = Field(default=["mock"], min_length=1)
    daraja_mock_base_url: str = "http://127.0.0.1:8000/sandbox/daraja"
    # Where the mock posts its callbacks. Unset means PUBLIC_BASE_URL. On AWS this is the
    # task's own port, so mock callbacks do not leave the container.
    daraja_mock_callback_base_url: str | None = None
    daraja_consumer_key: str = "sandbox"
    daraja_consumer_secret: str = "sandbox"
    daraja_shortcode: str = "174379"
    daraja_passkey: str = "sandbox-passkey"
    daraja_base_url: str = "https://sandbox.safaricom.co.ke"
    # Daraja sandbox STK prompts reach real handsets, so a public demo limits the
    # sandbox rail to the owner's test phones. Empty means any phone (local only).
    daraja_sandbox_allowed_phones: list[str] = []

    # Where Daraja sends STK callbacks. The real sandbox needs a public https URL.
    public_base_url: str = "http://127.0.0.1:8000"
    # Secret path segment of the callback URL. Hex, because Daraja rejects some words in URLs.
    # Random per process unless set; every API instance behind one URL must share it.
    stk_callback_token: str = Field(default_factory=lambda: secrets.token_hex(16), min_length=16)
    stk_query_after_seconds: int = 60
    stk_expire_after_seconds: int = 300
    stk_query_interval_seconds: int = 15

    # Transactional outbox worker: a failed job waits base * 2^(attempt-1) seconds
    # (capped), and goes to the dead-letter queue after max_attempts. A claimed job
    # that is not finished within lease_seconds is handed to another worker.
    outbox_max_attempts: int = Field(default=6, ge=1)
    outbox_backoff_base_seconds: float = Field(default=5.0, gt=0)
    outbox_backoff_cap_seconds: float = Field(default=900.0, gt=0)
    outbox_lease_seconds: int = Field(default=60, ge=1)
    outbox_poll_seconds: float = Field(default=1.0, gt=0)

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

    rate_limits_enabled: bool = True
    # Proxies in front of the API that append to X-Forwarded-For (CloudFront + ALB = 2).
    # Leave at 0 when the API is reached directly, or clients could forge their IP.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)
    # Browser origins allowed to call the API with cookies; only `next dev` needs one.
    # The compose stack and AWS serve the web app and the API from one origin.
    cors_origins: list[str] = []

    @model_validator(mode="after")
    def refuse_real_money(self) -> Settings:
        if self.sandbox_mode is not True:
            raise ValueError(
                "Refusing to start: X Money for Kenya is a sandbox prototype and "
                "cannot be configured to move real money."
            )
        try:
            assert_sandbox_daraja_host(self.daraja_base_url)
            assert_sandbox_daraja_host(self.daraja_mock_base_url)
        except SandboxViolation as exc:
            raise ValueError(f"Refusing to start: {exc}") from exc
        try:
            self.daraja_sandbox_allowed_phones = [
                normalize_phone(phone) for phone in self.daraja_sandbox_allowed_phones
            ]
        except InvalidPhone as exc:
            raise ValueError(f"DARAJA_SANDBOX_ALLOWED_PHONES: {exc}") from exc
        if len(set(self.payment_rails)) != len(self.payment_rails):
            raise ValueError("PAYMENT_RAILS lists a rail twice")
        if "sandbox" in self.payment_rails:
            placeholders = (
                (self.daraja_consumer_key, "sandbox"),
                (self.daraja_consumer_secret, "sandbox"),
                (self.daraja_passkey, "sandbox-passkey"),
            )
            if any(value == placeholder for value, placeholder in placeholders):
                raise ValueError(
                    "Refusing to start: the sandbox rail needs DARAJA_CONSUMER_KEY, "
                    "DARAJA_CONSUMER_SECRET, and DARAJA_PASSKEY from the Daraja portal."
                )
            if self.is_public and not self.daraja_sandbox_allowed_phones:
                raise ValueError(
                    "Refusing to start: a public demo with the sandbox rail must set "
                    "DARAJA_SANDBOX_ALLOWED_PHONES, or any visitor could prompt any handset."
                )
        if self.db_host is not None and not (self.db_username and self.db_password):
            raise ValueError("DB_HOST is set, so DB_USERNAME and DB_PASSWORD must be too")
        if self.sandbox_journal_enabled and self.is_public:
            raise ValueError(
                "Refusing to start: SANDBOX_JOURNAL_ENABLED is for local development and "
                "cannot be on when PUBLIC_BASE_URL is a public https URL."
            )
        return self

    @property
    def is_public(self) -> bool:
        return self.public_base_url.lower().startswith("https://")

    @property
    def sqlalchemy_url(self) -> str:
        if self.db_host is None:
            return self.database_url
        return URL.create(
            "postgresql+psycopg",
            username=self.db_username,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"sslmode": self.db_sslmode},
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
