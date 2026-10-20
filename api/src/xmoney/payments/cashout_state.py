"""Cash-out state machine. Migration 0011 enforces the same table in Postgres.

    initiated -> pending      B2C accepted (ConversationID)
    initiated -> failed       B2C refused, or never accepted in time (hold released)
    pending   -> succeeded    result callback: paid (hold settled to float)
    pending   -> failed       result callback: not paid (hold released)
    pending   -> expired      timeout callback or no answer in time (hold stays)
    expired   -> succeeded    a late paid result
    expired   -> failed       a late unpaid result

`expired` means we stopped waiting with funds still in `system:mpesa_clearing`.
A timeout is not a refund. Reconciliation (later) still owns unexplained holds.
"""

from __future__ import annotations

from datetime import datetime

from xmoney.errors import LedgerError
from xmoney.payments.models import Cashout, CashoutStatus

S = CashoutStatus

ALLOWED: dict[CashoutStatus, frozenset[CashoutStatus]] = {
    S.INITIATED: frozenset({S.PENDING, S.FAILED}),
    S.PENDING: frozenset({S.SUCCEEDED, S.FAILED, S.EXPIRED}),
    S.EXPIRED: frozenset({S.SUCCEEDED, S.FAILED}),
    S.SUCCEEDED: frozenset(),
    S.FAILED: frozenset(),
}

FINAL = frozenset({S.SUCCEEDED, S.FAILED})


def transition(cashout: Cashout, target: CashoutStatus, now: datetime) -> None:
    current = CashoutStatus(cashout.status)
    if target not in ALLOWED[current]:
        raise LedgerError(f"illegal cash-out transition {current} -> {target}")
    cashout.status = target.value
    cashout.updated_at = now
    if target is not S.PENDING:
        cashout.resolved_at = now
