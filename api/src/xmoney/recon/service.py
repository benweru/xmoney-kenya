"""Classify ledger and rail differences. Closed suspense quiets a subject (ADR 020)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xmoney.db import release_read_transaction
from xmoney.errors import ProviderError, RailUnavailable
from xmoney.ledger.models import LedgerAccount, Posting
from xmoney.ledger.service import trial_totals
from xmoney.payments.deps import Rails
from xmoney.payments.models import (
    CallbackDisposition,
    Cashout,
    CashoutStatus,
    StkCallbackLog,
    Topup,
)
from xmoney.payments.provider import Outcome
from xmoney.recon.models import BreakKind, ReconBreak, ReconRun


@dataclass(frozen=True)
class ReconReport:
    run_id: UUID
    break_count: int
    unexplained_count: int
    kinds: tuple[str, ...]


def run_recon(session: Session, rails: Rails | None = None) -> ReconReport:
    """Walk wallets, callbacks, and (optionally) STK Query. Commits one run."""
    release_read_transaction(session)
    run_id = uuid4()
    with session.begin():
        session.add(ReconRun(id=run_id, started_at=datetime.now(UTC)))
        found: list[ReconBreak] = []
        found.extend(_trial(session, run_id))
        found.extend(_wallet_drift(session, run_id))
        quieted = _quieted_subjects(session)
        found.extend(_callback_breaks(session, run_id, quieted))
        found.extend(_expired_holds(session, run_id, quieted))
        if rails is not None:
            found.extend(_rail_missing(session, rails, run_id, quieted))
        for row in found:
            session.add(row)
        run = session.get(ReconRun, run_id)
        assert run is not None
        run.break_count = len(found)
        run.unexplained_count = 0
        run.finished_at = datetime.now(UTC)
        kinds = tuple(row.kind for row in found)
        return ReconReport(run_id, len(found), 0, kinds)


def _trial(session: Session, run_id: UUID) -> list[ReconBreak]:
    debits, credits = trial_totals(session)
    if debits == credits:
        return []
    return [
        _break(
            run_id,
            BreakKind.TRIAL_UNBALANCED,
            "ledger",
            None,
            f"trial totals differ: debits {debits} credits {credits}",
            our_cents=debits,
            their_cents=credits,
        )
    ]


def _wallet_drift(session: Session, run_id: UUID) -> list[ReconBreak]:
    debit_sum = func.coalesce(
        func.sum(Posting.amount_cents).filter(Posting.direction == "debit"),
        0,
    )
    credit_sum = func.coalesce(
        func.sum(Posting.amount_cents).filter(Posting.direction == "credit"),
        0,
    )
    posted = (
        select(
            Posting.account_id.label("account_id"),
            debit_sum.label("debit_cents"),
            credit_sum.label("credit_cents"),
        )
        .group_by(Posting.account_id)
        .subquery()
    )
    rows = session.execute(
        select(
            LedgerAccount.id,
            LedgerAccount.code,
            LedgerAccount.running_debit_cents,
            LedgerAccount.running_credit_cents,
            func.coalesce(posted.c.debit_cents, 0),
            func.coalesce(posted.c.credit_cents, 0),
        )
        .outerjoin(posted, posted.c.account_id == LedgerAccount.id)
        .where(LedgerAccount.allow_negative.is_(False))
    ).all()
    found: list[ReconBreak] = []
    for account_id, code, run_d, run_c, post_d, post_c in rows:
        if int(run_d) == int(post_d) and int(run_c) == int(post_c):
            continue
        found.append(
            _break(
                run_id,
                BreakKind.RUNNING_BALANCE_DRIFT,
                "wallet",
                account_id,
                (
                    f"{code} running debit/credit {int(run_d)}/{int(run_c)} "
                    f"but postings {int(post_d)}/{int(post_c)}"
                ),
                our_cents=int(run_c) - int(run_d),
                their_cents=int(post_c) - int(post_d),
            )
        )
    return found


def _quieted_subjects(session: Session) -> set[tuple[str, UUID]]:
    rows = session.execute(
        select(ReconBreak.subject_type, ReconBreak.subject_id).where(
            ReconBreak.quieted_at.is_not(None),
            ReconBreak.subject_id.is_not(None),
        )
    ).all()
    return {
        (subject_type, subject_id) for subject_type, subject_id in rows if subject_id is not None
    }


def _callback_breaks(
    session: Session, run_id: UUID, quieted: set[tuple[str, UUID]]
) -> list[ReconBreak]:
    rows = session.scalars(
        select(StkCallbackLog).where(
            StkCallbackLog.disposition.in_(
                (CallbackDisposition.AMOUNT_MISMATCH.value, CallbackDisposition.UNMATCHED.value)
            )
        )
    ).all()
    found: list[ReconBreak] = []
    for row in rows:
        if ("callback", row.id) in quieted:
            continue
        if row.disposition == CallbackDisposition.AMOUNT_MISMATCH.value:
            found.append(
                _break(
                    run_id,
                    BreakKind.AMOUNT_MISMATCH,
                    "callback",
                    row.id,
                    f"STK callback {row.checkout_request_id} amount did not match the top-up",
                )
            )
        else:
            found.append(
                _break(
                    run_id,
                    BreakKind.MISSING_ON_LEDGER,
                    "callback",
                    row.id,
                    f"STK callback {row.checkout_request_id} matched no top-up",
                )
            )
    return found


def _expired_holds(
    session: Session, run_id: UUID, quieted: set[tuple[str, UUID]]
) -> list[ReconBreak]:
    rows = session.scalars(
        select(Cashout).where(
            Cashout.status == CashoutStatus.EXPIRED.value,
            Cashout.release_journal_entry_id.is_(None),
        )
    ).all()
    return [
        _break(
            run_id,
            BreakKind.IN_FLIGHT_HOLD,
            "cashout",
            row.id,
            "expired cash-out still held in clearing until a late result or suspense",
            our_cents=row.amount_cents,
        )
        for row in rows
        if ("cashout", row.id) not in quieted
    ]


def _rail_missing(
    session: Session, rails: Rails, run_id: UUID, quieted: set[tuple[str, UUID]]
) -> list[ReconBreak]:
    rows = session.scalars(
        select(Topup).where(
            Topup.status == "succeeded",
            Topup.checkout_request_id.is_not(None),
        )
    ).all()
    found: list[ReconBreak] = []
    for topup in rows:
        if ("topup", topup.id) in quieted:
            continue
        assert topup.checkout_request_id is not None
        provider = rails.for_topup(topup.provider)
        if provider is None:
            found.append(
                _break(
                    run_id,
                    BreakKind.MISSING_ON_RAIL,
                    "topup",
                    topup.id,
                    f"rail {topup.provider} is no longer offered",
                    our_cents=topup.amount_cents,
                )
            )
            continue
        try:
            queried = provider.stk_query(topup.checkout_request_id)
        except (ProviderError, RailUnavailable, OSError) as exc:
            found.append(
                _break(
                    run_id,
                    BreakKind.MISSING_ON_RAIL,
                    "topup",
                    topup.id,
                    f"STK Query failed for {topup.checkout_request_id}: {exc}",
                    our_cents=topup.amount_cents,
                )
            )
            continue
        if queried.processing:
            continue
        if queried.outcome is Outcome.SUCCESS:
            continue
        found.append(
            _break(
                run_id,
                BreakKind.MISSING_ON_RAIL,
                "topup",
                topup.id,
                (
                    f"ledger credited {topup.checkout_request_id} but STK Query "
                    f"says {queried.result_desc}"
                ),
                our_cents=topup.amount_cents,
            )
        )
    return found


def _break(
    run_id: UUID,
    kind: BreakKind,
    subject_type: str,
    subject_id: UUID | None,
    detail: str,
    *,
    our_cents: int | None = None,
    their_cents: int | None = None,
) -> ReconBreak:
    return ReconBreak(
        id=uuid4(),
        run_id=run_id,
        kind=kind.value,
        subject_type=subject_type,
        subject_id=subject_id,
        our_cents=our_cents,
        their_cents=their_cents,
        detail=detail[:500],
    )
