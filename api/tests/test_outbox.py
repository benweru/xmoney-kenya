"""The outbox: atomic with its cause, retried with backoff, dead-lettered, never run twice."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from xmoney.outbox import service
from xmoney.outbox.models import JobStatus, OutboxJob
from xmoney.outbox.service import Claim, OutboxError, PermanentFailure, backoff_seconds
from xmoney.outbox.worker import Outcome, drain, run_one

T0 = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)
KIND = "test.job"


def _job(session: Session, job_id: UUID) -> OutboxJob:
    session.expire_all()
    job = session.get(OutboxJob, job_id)
    assert job is not None
    return job


def _enqueue(session: Session, **kwargs: object) -> UUID:
    session.rollback()  # end any read transaction the test left open
    with session.begin():
        return service.enqueue(session, KIND, {"n": 1}, now=T0, **kwargs)  # type: ignore[arg-type]


# --- backoff -------------------------------------------------------------------


def test_backoff_doubles_then_stops_at_the_cap() -> None:
    delays = [backoff_seconds(a, base=5, cap=60) for a in range(1, 8)]
    assert delays == [5, 10, 20, 40, 60, 60, 60]


@given(
    attempt=st.integers(min_value=1, max_value=10_000),
    base=st.floats(min_value=0.01, max_value=100),
    cap=st.floats(min_value=0.01, max_value=10_000),
    jitter=st.floats(min_value=0, max_value=0.99),
    roll=st.floats(min_value=0, max_value=1),
)
def test_backoff_is_bounded_by_the_cap_and_by_its_jitter(
    attempt: int, base: float, cap: float, jitter: float, roll: float
) -> None:
    plain = backoff_seconds(attempt, base=base, cap=cap)
    jittered = backoff_seconds(attempt, base=base, cap=cap, jitter=jitter, rng=lambda: roll)
    assert 0 < plain <= cap
    assert plain * (1 - jitter) - 1e-9 <= jittered <= plain + 1e-9


@given(attempt=st.integers(min_value=1, max_value=200))
def test_backoff_never_shrinks_as_attempts_grow(attempt: int) -> None:
    assert backoff_seconds(attempt + 1, base=3, cap=500) >= backoff_seconds(
        attempt, base=3, cap=500
    )


def test_backoff_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        backoff_seconds(0, base=1, cap=1)
    with pytest.raises(ValueError):
        backoff_seconds(1, base=1, cap=1, jitter=1.0)


# --- enqueue is part of the caller's transaction --------------------------------


def test_job_exists_only_if_the_business_transaction_committed(db: Session) -> None:
    with pytest.raises(RuntimeError, match="payment write failed"), db.begin():
        service.enqueue(db, KIND, {"n": 1}, now=T0)
        raise RuntimeError("payment write failed")
    assert db.scalar(select(func.count()).select_from(OutboxJob)) == 0
    db.rollback()

    job_id = _enqueue(db)
    assert _job(db, job_id).status == JobStatus.PENDING.value


def test_dedupe_key_returns_the_first_job_even_after_it_finished(db: Session) -> None:
    first = _enqueue(db, dedupe_key="topup:1")
    assert _enqueue(db, dedupe_key="topup:1") == first
    assert run_one(db, {KIND: lambda _c: None}, now=T0) is Outcome.DONE
    assert _enqueue(db, dedupe_key="topup:1") == first
    assert db.scalar(select(func.count()).select_from(OutboxJob)) == 1
    # The same key under another kind is a different job.
    db.rollback()
    with db.begin():
        other = service.enqueue(db, "test.other", {}, dedupe_key="topup:1", now=T0)
    assert other != first


def test_enqueue_rejects_bad_input(db: Session) -> None:
    with pytest.raises(OutboxError), db.begin():
        service.enqueue(db, "", {})
    with pytest.raises(OutboxError), db.begin():
        service.enqueue(db, KIND, {}, max_attempts=0)


# --- running jobs ---------------------------------------------------------------


def test_a_job_runs_once_and_is_done(db: Session) -> None:
    job_id = _enqueue(db)
    seen: list[Claim] = []
    assert run_one(db, {KIND: seen.append}, now=T0) is Outcome.DONE
    assert [c.payload for c in seen] == [{"n": 1}]
    job = _job(db, job_id)
    assert (job.status, job.attempts, job.last_error) == ("done", 1, None)
    assert job.completed_at is not None and job.lease_token is None
    assert run_one(db, {KIND: seen.append}, now=T0) is Outcome.IDLE
    assert len(seen) == 1


def test_a_job_is_not_run_before_it_is_due(db: Session) -> None:
    job_id = _enqueue(db, run_at=T0 + timedelta(minutes=5))
    assert run_one(db, {KIND: lambda _c: None}, now=T0) is Outcome.IDLE
    assert run_one(db, {KIND: lambda _c: None}, now=T0 + timedelta(minutes=5)) is Outcome.DONE
    assert _job(db, job_id).status == "done"


def test_a_worker_ignores_kinds_it_has_no_handler_for(db: Session) -> None:
    job_id = _enqueue(db)
    assert run_one(db, {"test.unrelated": lambda _c: None}, now=T0) is Outcome.IDLE
    job = _job(db, job_id)
    assert (job.status, job.attempts) == ("pending", 0)


def test_failures_back_off_and_then_succeed(db: Session) -> None:
    job_id = _enqueue(db)
    calls: list[int] = []

    def flaky(claim: Claim) -> None:
        calls.append(claim.attempt)
        if claim.attempt < 3:
            raise ConnectionError("Daraja 500")

    now = T0
    for expected_wait in (5, 10):
        assert run_one(db, {KIND: flaky}, now=now) is Outcome.RETRY
        job = _job(db, job_id)
        wait = (job.run_at - now).total_seconds()
        assert expected_wait * 0.8 <= wait <= expected_wait  # up to 20% jitter
        assert job.last_error == "ConnectionError: Daraja 500"
        assert run_one(db, {KIND: flaky}, now=now) is Outcome.IDLE  # still backing off
        now = job.run_at
    assert run_one(db, {KIND: flaky}, now=now) is Outcome.DONE
    assert calls == [1, 2, 3]
    job = _job(db, job_id)
    assert (job.status, job.attempts, job.last_error) == ("done", 3, None)


def test_a_job_that_keeps_failing_goes_to_the_dlq_and_can_be_replayed(db: Session) -> None:
    job_id = _enqueue(db, max_attempts=3)
    always_fails = {KIND: _boom}
    now = T0
    outcomes = []
    for _ in range(3):
        outcomes.append(run_one(db, always_fails, now=now))
        now = _job(db, job_id).run_at
    assert outcomes == [Outcome.RETRY, Outcome.RETRY, Outcome.DEAD]
    dead = _job(db, job_id)
    assert (dead.status, dead.attempts) == ("dead", 3)
    assert dead.last_error is not None and "nope" in dead.last_error
    assert [j.id for j in service.dead_jobs(db)] == [job_id]
    assert run_one(db, always_fails, now=now + timedelta(days=1)) is Outcome.IDLE

    service.replay(db, job_id, now=now)
    replayed = _job(db, job_id)
    assert (replayed.status, replayed.attempts, replayed.replays) == ("pending", 0, 1)
    assert run_one(db, {KIND: lambda _c: None}, now=now) is Outcome.DONE
    assert service.dead_jobs(db) == []


def test_a_permanent_failure_skips_the_retries(db: Session) -> None:
    job_id = _enqueue(db)

    def refuse(_claim: Claim) -> None:
        raise PermanentFailure("phone number is not a Safaricom line")

    assert run_one(db, {KIND: refuse}, now=T0) is Outcome.DEAD
    job = _job(db, job_id)
    assert (job.status, job.attempts) == ("dead", 1)
    assert job.last_error == "PermanentFailure: phone number is not a Safaricom line"


def test_only_a_dead_job_can_be_replayed(db: Session) -> None:
    job_id = _enqueue(db)
    with pytest.raises(OutboxError, match="only a dead job"):
        service.replay(db, job_id)
    with pytest.raises(OutboxError, match="no such job"):
        service.replay(db, UUID(int=1))


# --- a worker that dies mid-job -------------------------------------------------


def test_a_killed_workers_job_is_retried_after_its_lease_lapses(db: Session) -> None:
    job_id = _enqueue(db)
    dead_workers_claim = service.claim_next(db, kinds=[KIND], now=T0, lease_seconds=60)
    assert dead_workers_claim is not None and dead_workers_claim.attempt == 1
    # ...and the worker is killed here: no finish, no fail.

    just_before = T0 + timedelta(seconds=59)
    assert service.claim_next(db, kinds=[KIND], now=just_before, lease_seconds=60) is None

    after = T0 + timedelta(seconds=61)
    assert run_one(db, {KIND: lambda _c: None}, now=after) is Outcome.DONE
    job = _job(db, job_id)
    assert (job.status, job.attempts) == ("done", 2)


def test_a_slow_worker_cannot_overwrite_the_one_that_took_over(db: Session) -> None:
    _enqueue(db)
    slow = service.claim_next(db, kinds=[KIND], now=T0, lease_seconds=60)
    assert slow is not None
    later = T0 + timedelta(seconds=120)
    fast = service.claim_next(db, kinds=[KIND], now=later, lease_seconds=60)
    assert fast is not None and fast.token != slow.token

    assert service.finish(db, fast, later) is True
    assert service.finish(db, slow, later) is False
    assert service.fail(db, slow, "late", now=later) is None
    assert _job(db, slow.id).status == "done"


def test_a_job_that_keeps_killing_its_worker_is_buried_not_looped(db: Session) -> None:
    job_id = _enqueue(db, max_attempts=2)
    now = T0
    for attempt in (1, 2):
        claim = service.claim_next(db, kinds=[KIND], now=now, lease_seconds=60)
        assert claim is not None and claim.attempt == attempt
        now += timedelta(seconds=61)  # the worker died; the lease lapses
    assert service.claim_next(db, kinds=[KIND], now=now, lease_seconds=60) is None
    job = _job(db, job_id)
    assert job.status == "dead"
    assert job.last_error is not None and "never reported" in job.last_error


# --- many workers ---------------------------------------------------------------


def test_concurrent_workers_never_run_the_same_job_twice(engine: Engine) -> None:
    jobs = 40
    with Session(engine) as seed, seed.begin():
        for n in range(jobs):
            service.enqueue(seed, KIND, {"n": n})

    handled: list[int] = []
    guard = threading.Lock()
    errors: list[BaseException] = []

    def handler(claim: Claim) -> None:
        with guard:
            handled.append(claim.payload["n"])

    def worker() -> None:
        try:
            with Session(engine) as session:
                drain(session, {KIND: handler})
        except BaseException as exc:  # surfaced below; a thread must not swallow it
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, errors
    assert sorted(handled) == list(range(jobs))
    with Session(engine) as check:
        statuses = check.scalars(select(OutboxJob.status)).all()
        assert statuses == ["done"] * jobs


def _boom(_claim: Claim) -> None:
    raise RuntimeError("nope")

