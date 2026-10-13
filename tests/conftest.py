"""Postgres-backed fixtures. The suite truncates between tests and is not parallel-safe."""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator

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
                    "TRUNCATE TABLE postings, journal_entries, ledger_accounts, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
        with Session(engine) as session:
            seed_system_accounts(session)
            session.commit()


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
