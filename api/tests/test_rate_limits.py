"""Per-IP and per-user limits, counted in Postgres so every API task shares them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from typing import Self

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xmoney.errors import RateLimited
from xmoney.ratelimit import service
from xmoney.ratelimit.models import RateLimitHit
from xmoney.ratelimit.service import (
    REGISTER,
    SIGN_IN,
    START_CASHOUT,
    START_TOPUP,
    Limit,
    enforce,
    prune,
)

# Every limit's window starts on the hour, so no test can straddle a window boundary.
FROZEN_NOW = datetime(2026, 10, 13, 12, 0, 30, tzinfo=UTC)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        return cls.fromtimestamp(FROZEN_NOW.timestamp(), tz)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "datetime", _FrozenDatetime)


@pytest.fixture
def limits_on(configure) -> None:
    configure(RATE_LIMITS_ENABLED="true")


def _register(client, n: int, headers: dict[str, str] | None = None):
    return client.post(
        "/v1/users",
        json={"handle": f"user{n}", "phone": f"+2547123450{n:02d}", "pin": "2580"},
        headers=headers or {},
    )


def test_registration_is_limited_per_ip(client, limits_on) -> None:
    for n in range(REGISTER.limit):
        assert _register(client, n).status_code == 201
    refused = _register(client, REGISTER.limit)
    assert refused.status_code == 429
    assert refused.json()["error"] == "rate_limited"
    assert 1 <= int(refused.headers["Retry-After"]) <= REGISTER.window_seconds


def test_failed_attempts_count_toward_the_limit(client, limits_on) -> None:
    for _ in range(SIGN_IN.limit):
        wrong = client.post("/v1/auth/sign-in", json={"phone": "+254712345678", "pin": "9137"})
        assert wrong.status_code == 401
    refused = client.post("/v1/auth/sign-in", json={"phone": "+254712345678", "pin": "9137"})
    assert refused.status_code == 429


def test_forwarded_for_is_ignored_without_trusted_proxies(client, limits_on) -> None:
    for n in range(REGISTER.limit):
        assert _register(client, n, {"X-Forwarded-For": f"203.0.113.{n}"}).status_code == 201
    spoofed = _register(client, REGISTER.limit, {"X-Forwarded-For": "198.51.100.7"})
    assert spoofed.status_code == 429


def test_trusted_proxies_give_each_viewer_their_own_bucket(client, configure) -> None:
    configure(RATE_LIMITS_ENABLED="true", TRUSTED_PROXY_HOPS="2")
    edge = "130.176.0.1"
    for n in range(REGISTER.limit):
        headers = {"X-Forwarded-For": f"203.0.113.10, {edge}"}
        assert _register(client, n, headers).status_code == 201
    # The same viewer is refused, even when it prepends a forged address.
    forged = {"X-Forwarded-For": f"1.2.3.4, 203.0.113.10, {edge}"}
    assert _register(client, REGISTER.limit, forged).status_code == 429
    other_viewer = {"X-Forwarded-For": f"203.0.113.11, {edge}"}
    assert _register(client, REGISTER.limit + 1, other_viewer).status_code == 201


def test_top_ups_are_limited_per_user(client, sign_up, configure) -> None:
    configure(RATE_LIMITS_ENABLED="true", TOPUP_MAX_CENTS="100")
    sign_up("amina", "+254712345678")
    for n in range(START_TOPUP.limit):
        over_cap = client.post(
            "/v1/topups", json={"amount_cents": 200}, headers={"Idempotency-Key": f"t-{n}"}
        )
        assert over_cap.status_code == 422
    refused = client.post(
        "/v1/topups", json={"amount_cents": 200}, headers={"Idempotency-Key": "t-last"}
    )
    assert refused.status_code == 429


def test_cash_outs_are_limited_per_user(client, sign_up, configure) -> None:
    configure(RATE_LIMITS_ENABLED="true")
    sign_up("amina", "+254712345678")
    for n in range(START_CASHOUT.limit):
        overdrawn = client.post(
            "/v1/cashouts", json={"amount_cents": 100}, headers={"Idempotency-Key": f"c-{n}"}
        )
        assert overdrawn.status_code == 422
    refused = client.post(
        "/v1/cashouts", json={"amount_cents": 100}, headers={"Idempotency-Key": "c-last"}
    )
    assert refused.status_code == 429


def test_health_is_never_limited(client, configure) -> None:
    configure(RATE_LIMITS_ENABLED="true")
    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_counts_reset_with_the_window(db: Session, limits_on) -> None:
    limit = Limit("test", 2, 60)
    start = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
    enforce(db, limit, "10.0.0.1", now=start)
    enforce(db, limit, "10.0.0.1", now=start + timedelta(seconds=10))
    with pytest.raises(RateLimited) as refused:
        enforce(db, limit, "10.0.0.1", now=start + timedelta(seconds=45))
    assert refused.value.retry_after == 15
    enforce(db, limit, "10.0.0.2", now=start + timedelta(seconds=45))
    enforce(db, limit, "10.0.0.1", now=start + timedelta(seconds=60))


def test_buckets_store_hashes_and_old_windows_are_pruned(db: Session, limits_on) -> None:
    old = datetime(2026, 10, 1, tzinfo=UTC)
    enforce(db, Limit("test", 5, 60), "10.0.0.1", now=old)
    enforce(db, Limit("test", 5, 60), "10.0.0.1")
    buckets = db.scalars(select(RateLimitHit.bucket)).all()
    assert buckets and all("10.0.0.1" not in bucket for bucket in buckets)
    assert prune(db) == 1
    db.commit()
    assert db.scalar(select(func.count()).select_from(RateLimitHit)) == 1


def test_limits_can_be_switched_off(db: Session) -> None:
    for _ in range(3):
        enforce(db, Limit("test", 1, 60), "10.0.0.1")
    assert db.scalar(select(func.count()).select_from(RateLimitHit)) == 0
