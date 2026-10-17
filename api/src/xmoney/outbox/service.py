"""Outbox service: enqueue, claim, finish, fail, replay.

The rules, in one place:

* `enqueue` only adds a row to the caller's session. It never commits, so the
  job exists if and only if the business change that needs it was committed.
* `claim_next` takes one due job with `FOR UPDATE SKIP LOCKED` and leases it,
  counting the attempt at once. The lease, not a status, is what makes a job
  "running": a worker killed mid-job lets the lease lapse and the job is retried,
  and a job that keeps killing its worker runs out of attempts instead of looping.
* Handlers run outside any transaction, and delivery is at least once, so a
  handler must be idempotent (give the rail a stable idempotency key).
* `finish` and `fail` only act while the caller still holds the lease. A worker
  that was too slow cannot overwrite the result of the one that took over.
* A failed job waits with exponential backoff, then goes dead after
  `max_attempts`. Dead jobs are the dead-letter queue; `replay` puts one back.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from xmoney.config import get_settings
from xmoney.db import release_read_transaction
from xmoney.errors import LedgerError
from xmoney.outbox.models import JobStatus, OutboxJob

_ERROR_LIMIT = 2000


class OutboxError(LedgerError):
    """A caller asked the outbox for something it cannot do."""


class PermanentFailure(Exception):
    """Raised by a handler when retrying cannot help. The job goes straight to the DLQ."""


@dataclass(frozen=True)
class Claim:
    """A leased job. `token` proves the holder still owns the lease."""

    id: UUID
    kind: str
    payload: dict[str, Any]
    attempt: int
    max_attempts: int
    token: UUID


def backoff_seconds(
    attempt: int,
    *,
    base: float,
    cap: float,
    jitter: float = 0.0,
    rng: Callable[[], float] = random.random,
) -> float:
    """Seconds to wait after the given failed attempt (1 = the first failure).

    `base * 2^(attempt-1)`, capped. `jitter` is the fraction of the delay that may
    be shaved off at random, so a burst of failures does not retry in lockstep.
    The result is never above the cap and never below `(1 - jitter)` of the plain delay.
    """
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    if not 0.0 <= jitter < 1.0:
        raise ValueError("jitter must be in [0, 1)")
    exponent = min(attempt - 1, 60)  # keeps the float finite; the cap decides long before
    delay = min(cap, base * (2.0**exponent))
    return delay * (1.0 - jitter * rng())


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any],
    *,
    dedupe_key: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int | None = None,
    now: datetime | None = None,
) -> UUID:
    """Add a job inside the caller's transaction. Commit is the caller's, never ours.

    With a `dedupe_key`, a second enqueue of the same (kind, key) returns the first
    job's id and adds nothing, whether or not that job has finished.
    """
    if not kind or len(kind) > 60:
        raise OutboxError("job kind must be 1 to 60 characters")
    attempts = max_attempts if max_attempts is not None else get_settings().outbox_max_attempts
    if attempts < 1:
        raise OutboxError("max_attempts must be at least 1")
    now = now or datetime.now(UTC)
    job_id = uuid4()
    values = {
        "id": job_id,
        "kind": kind,
        "payload": payload,
        "dedupe_key": dedupe_key,
        "max_attempts": attempts,
        "run_at": run_at or now,
        "created_at": now,
        "updated_at": now,
    }
    if dedupe_key is None:
        session.add(OutboxJob(**values))
        session.flush()
        return job_id
    inserted: UUID | None = session.scalar(
        pg_insert(OutboxJob)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["kind", "dedupe_key"], index_where=text("dedupe_key IS NOT NULL")
        )
        .returning(OutboxJob.id)
    )
    if inserted is not None:
        return inserted
    existing = session.scalar(
        select(OutboxJob.id).where(OutboxJob.kind == kind, OutboxJob.dedupe_key == dedupe_key)
    )
    assert existing is not None
    return existing


def claim_next(
    session: Session,
    *,
    kinds: Collection[str],
    now: datetime | None = None,
    lease_seconds: int | None = None,
) -> Claim | None:
    """Lease the oldest due job of the given kinds, or return None if there is none."""
    if not kinds:
        return None
    now = now or datetime.now(UTC)
    lease = lease_seconds if lease_seconds is not None else get_settings().outbox_lease_seconds
    release_read_transaction(session)
    with session.begin():
        while True:
            job = session.scalar(
                select(OutboxJob)
                .where(
                    OutboxJob.status == JobStatus.PENDING.value,
                    OutboxJob.kind.in_(sorted(kinds)),
                    OutboxJob.run_at <= now,
                    (OutboxJob.lease_until.is_(None)) | (OutboxJob.lease_until <= now),
                )
                .order_by(OutboxJob.run_at, OutboxJob.created_at, OutboxJob.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            if job.attempts >= job.max_attempts:
                # The last attempt's worker never reported back (it died, or ran past
                # its lease). There is nothing left to retry with.
                _bury(job, "lease expired on the final attempt; the worker never reported", now)
                continue
            job.attempts += 1
            job.lease_until = now + timedelta(seconds=lease)
            job.lease_token = uuid4()
            job.updated_at = now
            return Claim(
                id=job.id,
                kind=job.kind,
                payload=dict(job.payload),
                attempt=job.attempts,
                max_attempts=job.max_attempts,
                token=job.lease_token,
            )


def finish(session: Session, claim: Claim, now: datetime | None = None) -> bool:
    """Mark a claimed job done. Returns False if the lease was lost to another worker."""
    now = now or datetime.now(UTC)
    release_read_transaction(session)
    with session.begin():
        result = session.execute(
            update(OutboxJob)
            .where(
                OutboxJob.id == claim.id,
                OutboxJob.lease_token == claim.token,
                OutboxJob.status == JobStatus.PENDING.value,
            )
            .values(
                status=JobStatus.DONE.value,
                completed_at=now,
                updated_at=now,
                lease_until=None,
                lease_token=None,
                last_error=None,
            )
        )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def fail(
    session: Session,
    claim: Claim,
    error: str,
    *,
    permanent: bool = False,
    now: datetime | None = None,
) -> JobStatus | None:
    """Record a failed attempt: retry later, or bury the job once it is out of attempts.

    Returns the job's new status (`pending` = will retry, `dead` = in the DLQ), or
    None if the lease was lost to another worker.
    """
    settings = get_settings()
    now = now or datetime.now(UTC)
    release_read_transaction(session)
    with session.begin():
        job = session.scalar(
            select(OutboxJob)
            .where(
                OutboxJob.id == claim.id,
                OutboxJob.lease_token == claim.token,
                OutboxJob.status == JobStatus.PENDING.value,
            )
            .with_for_update()
        )
        if job is None:
            return None
        if permanent or job.attempts >= job.max_attempts:
            _bury(job, error, now)
            return JobStatus.DEAD
        job.last_error = error[:_ERROR_LIMIT]
        job.run_at = now + timedelta(
            seconds=backoff_seconds(
                job.attempts,
                base=settings.outbox_backoff_base_seconds,
                cap=settings.outbox_backoff_cap_seconds,
                jitter=0.2,
            )
        )
        job.lease_until = None
        job.lease_token = None
        job.updated_at = now
        return JobStatus.PENDING


def replay(session: Session, job_id: UUID, now: datetime | None = None) -> None:
    """Put a dead job back in the queue with a fresh set of attempts."""
    now = now or datetime.now(UTC)
    release_read_transaction(session)
    with session.begin():
        job = session.scalar(select(OutboxJob).where(OutboxJob.id == job_id).with_for_update())
        if job is None:
            raise OutboxError("no such job")
        if job.status != JobStatus.DEAD.value:
            raise OutboxError(f"only a dead job can be replayed, this one is {job.status}")
        job.status = JobStatus.PENDING.value
        job.attempts = 0
        job.replays += 1
        job.run_at = now
        job.updated_at = now


def dead_jobs(session: Session, limit: int = 100) -> list[OutboxJob]:
    """The dead-letter queue, oldest first."""
    return list(
        session.scalars(
            select(OutboxJob)
            .where(OutboxJob.status == JobStatus.DEAD.value)
            .order_by(OutboxJob.updated_at, OutboxJob.id)
            .limit(limit)
        )
    )


def _bury(job: OutboxJob, error: str, now: datetime) -> None:
    job.status = JobStatus.DEAD.value
    job.last_error = error[:_ERROR_LIMIT]
    job.lease_until = None
    job.lease_token = None
    job.updated_at = now
