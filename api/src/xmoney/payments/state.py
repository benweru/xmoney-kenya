"""Top-up state machine. Migration 0004 enforces the same table in Postgres.

    initiated -> pending      push accepted
    initiated -> failed       push refused
    initiated -> expired      push never accepted in time
    pending   -> succeeded    callback or STK Query: paid
    pending   -> failed       callback or STK Query: cancelled, timed out, no funds
    pending   -> expired      no answer in time
    expired   -> succeeded    a late answer: paid
    expired   -> failed       a late answer: not paid

`expired` is "we stopped waiting", not "no money moved". A late callback or
query that proves the customer paid must still credit the wallet.
"""

from __future__ import annotations

from datetime import datetime

from xmoney.errors import LedgerError
from xmoney.payments.models import Topup, TopupStatus

S = TopupStatus

ALLOWED: dict[TopupStatus, frozenset[TopupStatus]] = {
    S.INITIATED: frozenset({S.PENDING, S.FAILED, S.EXPIRED}),
    S.PENDING: frozenset({S.SUCCEEDED, S.FAILED, S.EXPIRED}),
    S.EXPIRED: frozenset({S.SUCCEEDED, S.FAILED}),
    S.SUCCEEDED: frozenset(),
    S.FAILED: frozenset(),
}

FINAL = frozenset({S.SUCCEEDED, S.FAILED})


def transition(topup: Topup, target: TopupStatus, now: datetime) -> None:
    current = TopupStatus(topup.status)
    if target not in ALLOWED[current]:
        raise LedgerError(f"illegal top-up transition {current} -> {target}")
    topup.status = target.value
    topup.updated_at = now
    if target is not S.PENDING:
        topup.resolved_at = now
