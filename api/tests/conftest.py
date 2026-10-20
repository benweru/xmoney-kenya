"""Postgres-backed fixtures. The suite truncates between tests and is not parallel-safe."""

from __future__ import annotations

import os
import re
import warnings
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette.testclient` is deprecated",
    category=UserWarning,
)
from fastapi.testclient import TestClient  # noqa: E402

_DEFAULT_TEST_URL = "postgresql+psycopg://xmoney:xmoney@localhost:5432/xmoney_test"
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def pytest_configure(config: pytest.Config) -> None:
    chosen = (
        os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or _DEFAULT_TEST_URL
    )
    if "TEST_DATABASE_URL" not in os.environ and "xmoney_test" not in chosen:
        chosen = _DEFAULT_TEST_URL
    os.environ["DATABASE_URL"] = chosen
    os.environ["SANDBOX_MODE"] = "true"
    # Most tests sign many users up from one TestClient IP; test_rate_limits turns limits on.
    os.environ["RATE_LIMITS_ENABLED"] = "false"
    # Port 9 (discard) is closed, so mock callbacks never reach a dev server on :8000.
    os.environ["PUBLIC_BASE_URL"] = "http://127.0.0.1:9"
    # Hex only: a .env token with slashes would 404 the callback route.
    os.environ["STK_CALLBACK_TOKEN"] = "ab" * 16
    from xmoney.config import get_settings

    get_settings.cache_clear()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = os.environ["DATABASE_URL"]
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    command.upgrade(cfg, "head")
    eng = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=20,
        pool_timeout=10,
        connect_args={"options": "-c lock_timeout=8000 -c statement_timeout=20000"},
    )
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_tables(engine: Engine) -> Iterator[None]:
    yield
    from xmoney.ledger.service import seed_system_accounts, trial_totals

    try:
        with Session(engine) as session:
            debits, credits = trial_totals(session)
            assert debits == credits, f"trial balance drifted: debits={debits} credits={credits}"
    finally:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL xmoney.allow_truncate = 'on'"))
            conn.execute(
                text(
                    "TRUNCATE TABLE postings, journal_entries, ledger_accounts, users, "
                    "sandbox_inbox, rate_limit_hits, outbox_jobs, fee_schedules, "
                    "recon_breaks, recon_runs "
                    "RESTART IDENTITY CASCADE"
                )
            )
        with Session(engine) as session:
            from xmoney.transfers.fees import ensure_default_p2p_schedule

            seed_system_accounts(session)
            ensure_default_p2p_schedule(session)
            session.commit()


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """Override settings from environment variables for one test."""
    from xmoney.config import get_settings

    def _configure(**env: str) -> None:
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield _configure
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    from xmoney.db import get_db
    from xmoney.main import app

    def override() -> Iterator[Session]:
        session = Session(engine)
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


_CODE_RE = re.compile(r"code is (\d{6})")


@pytest.fixture
def sign_up(client: TestClient) -> Callable[..., dict[str, Any]]:
    """Register a user with a PIN and sign them in on `http` (default: `client`)."""

    def _sign_up(
        handle: str, phone: str, *, pin: str = "2580", http: TestClient | None = None
    ) -> dict[str, Any]:
        http = http or client
        created = http.post("/v1/users", json={"handle": handle, "phone": phone, "pin": pin})
        assert created.status_code == 201, created.text
        challenge = http.post("/v1/auth/sign-in", json={"phone": phone, "pin": pin})
        assert challenge.status_code == 200, challenge.text
        inbox = http.get("/v1/sandbox/inbox", params={"phone": phone}).json()
        match = _CODE_RE.search(inbox[0]["body"])
        assert match is not None
        verified = http.post(
            "/v1/auth/verify",
            json={"challenge_id": challenge.json()["challenge_id"], "code": match.group(1)},
        )
        assert verified.status_code == 200, verified.text
        body: dict[str, Any] = verified.json()
        return body

    return _sign_up
