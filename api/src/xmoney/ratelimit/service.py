"""Fixed-window rate limits counted in Postgres.

Every API task behind the load balancer shares one counter per bucket, so the
limit holds however many tasks are running. A fixed window lets a client burst
up to twice the limit across a window boundary; that is acceptable for a demo
and keeps the whole limiter to one upsert.

Buckets store a hash of the IP or user id, so the table holds no raw addresses.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from xmoney.config import get_settings
from xmoney.errors import RateLimited
from xmoney.ratelimit.models import RateLimitHit

_PRUNE_PROBABILITY = 0.01
_KEEP_FOR = timedelta(days=1)


@dataclass(frozen=True)
class Limit:
    scope: str
    limit: int
    window_seconds: int


# Per IP, every /v1 and /sandbox request. Polling a top-up once a second fits well inside it.
EVERY_REQUEST = Limit("ip", 300, 60)
REGISTER = Limit("register", 10, 3600)
SIGN_IN = Limit("sign-in", 20, 600)
VERIFY_CODE = Limit("verify", 20, 600)
READ_INBOX = Limit("inbox", 60, 60)
LOOK_UP_HANDLE = Limit("handle", 60, 60)
# Per signed-in user.
START_TOPUP = Limit("topup", 10, 3600)
START_CASHOUT = Limit("cashout", 10, 3600)
SEND = Limit("send", 30, 600)


def enforce(session: Session, limit: Limit, identity: str, now: datetime | None = None) -> None:
    """Count one request for `identity` and raise RateLimited once it is over the limit.

    The count commits immediately, so a request that fails later still counts.
    """
    if not get_settings().rate_limits_enabled:
        return
    now = now or datetime.now(UTC)
    window_start = _window_start(now, limit.window_seconds)
    statement = (
        insert(RateLimitHit)
        .values(bucket=_bucket(limit.scope, identity), window_start=window_start, hits=1)
        .on_conflict_do_update(
            index_elements=[RateLimitHit.bucket, RateLimitHit.window_start],
            set_={"hits": RateLimitHit.hits + 1},
        )
        .returning(RateLimitHit.hits)
    )
    hits = session.execute(statement).scalar_one()
    if random.random() < _PRUNE_PROBABILITY:
        prune(session, now)
    session.commit()
    if hits > limit.limit:
        window_end = window_start + timedelta(seconds=limit.window_seconds)
        retry_after = max(1, math.ceil((window_end - now).total_seconds()))
        raise RateLimited(
            f"too many {limit.scope} requests; try again in {retry_after} s",
            retry_after=retry_after,
        )


def prune(session: Session, now: datetime | None = None) -> int:
    """Delete windows that ended long ago. The caller commits."""
    cutoff = (now or datetime.now(UTC)) - _KEEP_FOR
    result = session.execute(delete(RateLimitHit).where(RateLimitHit.window_start < cutoff))
    return int(getattr(result, "rowcount", 0) or 0)


def _window_start(now: datetime, window_seconds: int) -> datetime:
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % window_seconds, UTC)


def _bucket(scope: str, identity: str) -> str:
    digest = hashlib.sha256(f"{scope}:{identity}".encode()).hexdigest()[:40]
    return f"{scope}:{digest}"
