"""The outbox worker: claim a job, run its handler, record the outcome.

Run it with `xmoney-outbox-worker` (loops until SIGTERM) or `--once` (drain what is
due, then exit; handy for tests and one-off ECS tasks).
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from xmoney.config import get_settings
from xmoney.db import get_sessionmaker, import_mapped_tables
from xmoney.outbox import service
from xmoney.outbox.service import Claim, PermanentFailure

logger = logging.getLogger("xmoney.outbox")

Handler = Callable[[Claim], None]


class Outcome(StrEnum):
    IDLE = "idle"
    DONE = "done"
    RETRY = "retry"
    DEAD = "dead"
    LEASE_LOST = "lease_lost"


@dataclass(frozen=True)
class Tally:
    done: int = 0
    retried: int = 0
    dead: int = 0
    lease_lost: int = 0

    @property
    def total(self) -> int:
        return self.done + self.retried + self.dead + self.lease_lost


def run_one(
    session: Session, handlers: Mapping[str, Handler], now: datetime | None = None
) -> Outcome:
    """Claim and run at most one due job. Handlers only run for kinds registered here."""
    claim = service.claim_next(session, kinds=handlers.keys(), now=now)
    if claim is None:
        return Outcome.IDLE
    try:
        handlers[claim.kind](claim)
    except PermanentFailure as exc:
        logger.warning("job %s (%s) failed permanently: %s", claim.id, claim.kind, exc)
        return _after_failure(session, claim, _describe(exc), permanent=True, now=now)
    except Exception as exc:
        logger.warning(
            "job %s (%s) attempt %d/%d failed: %s",
            claim.id,
            claim.kind,
            claim.attempt,
            claim.max_attempts,
            exc,
            exc_info=True,
        )
        return _after_failure(session, claim, _describe(exc), permanent=False, now=now)
    if service.finish(session, claim, now):
        return Outcome.DONE
    logger.warning("job %s (%s) finished after its lease was lost", claim.id, claim.kind)
    return Outcome.LEASE_LOST


def drain(
    session: Session,
    handlers: Mapping[str, Handler],
    *,
    now: datetime | None = None,
    limit: int = 1000,
) -> Tally:
    """Run due jobs until none are left (or `limit` ran). Retried jobs wait out their backoff."""
    counts = {Outcome.DONE: 0, Outcome.RETRY: 0, Outcome.DEAD: 0, Outcome.LEASE_LOST: 0}
    for _ in range(limit):
        outcome = run_one(session, handlers, now=now)
        if outcome is Outcome.IDLE:
            break
        counts[outcome] += 1
    return Tally(
        done=counts[Outcome.DONE],
        retried=counts[Outcome.RETRY],
        dead=counts[Outcome.DEAD],
        lease_lost=counts[Outcome.LEASE_LOST],
    )


def run_forever(
    handlers: Mapping[str, Handler], stop: threading.Event, *, poll_seconds: float | None = None
) -> None:
    """Poll until `stop` is set. The current job always finishes first."""
    poll = poll_seconds if poll_seconds is not None else get_settings().outbox_poll_seconds
    sessions = get_sessionmaker()
    while not stop.is_set():
        try:
            with sessions() as session:
                outcome = run_one(session, handlers)
        except Exception:
            # The database is unreachable or restarting. Jobs are safe in their rows.
            logger.exception("outbox worker could not reach the queue; retrying")
            outcome = Outcome.IDLE
        if outcome is Outcome.IDLE:
            stop.wait(poll)


def default_handlers() -> dict[str, Handler]:
    """Job kinds this worker serves. Feature modules register theirs here."""
    import_mapped_tables()
    from xmoney.payments.jobs import production_handlers

    return production_handlers()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the xMoney outbox worker.")
    parser.add_argument("--once", action="store_true", help="drain due jobs, then exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    handlers = default_handlers()
    if not handlers:
        logger.warning("no job handlers are registered; the worker will idle")
    if args.once:
        with get_sessionmaker()() as session:
            tally = drain(session, handlers)
        logger.info(
            "outbox: %d done, %d retried, %d dead, %d lease lost",
            tally.done,
            tally.retried,
            tally.dead,
            tally.lease_lost,
        )
        return
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    logger.info("outbox worker started (kinds: %s)", ", ".join(sorted(handlers)) or "none")
    run_forever(handlers, stop)
    logger.info("outbox worker stopped")


def _after_failure(
    session: Session, claim: Claim, error: str, *, permanent: bool, now: datetime | None
) -> Outcome:
    status = service.fail(session, claim, error, permanent=permanent, now=now)
    if status is None:
        return Outcome.LEASE_LOST
    return Outcome.DEAD if status.value == "dead" else Outcome.RETRY


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


if __name__ == "__main__":
    main()
