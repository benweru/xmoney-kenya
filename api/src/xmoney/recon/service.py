"""Classify ledger and rail differences. Closed suspense quiets a subject (ADR 020)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

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
    TopupStatus,
)
from xmoney.payments.provider import Outcome, PaymentsProvider, SettlementRow
from xmoney.recon.models import BreakKind, ReconBreak, ReconRun

_SETTLEMENT_NS = uuid5(NAMESPACE_URL, "https://xmoney.kenya/recon/settlement")


@dataclass(frozen=True)
class ReconReport:
    run_id: UUID
    break_count: int
    unexplained_count: int
    kinds: tuple[str, ...]


@dataclass
class _Walk:
    run_id: UUID
    quieted: set[tuple[str, UUID]]
    checkouts: set[str] = field(default_factory=set)
    receipts: set[str] = field(default_factory=set)


def run_recon(session: Session, rails: Rails | None = None) -> ReconReport:
    """Walk wallets, callbacks, settlement, and (optionally) STK Query. Commits one run."""
    release_read_transaction(session)
    run_id = uuid4()
    with session.begin():
        session.add(ReconRun(id=run_id, started_at=datetime.now(UTC)))
        found: list[ReconBreak] = []
        found.extend(_trial(session, run_id))
        found.extend(_wallet_drift(session, run_id))
        walk = _Walk(run_id=run_id, quieted=_quieted_subjects(session))
        _load_quieted_rail_keys(session, walk)
        found.extend(_callback_breaks(session, walk))
        found.extend(_expired_holds(session, walk))
        if rails is not None:
            found.extend(_settlement_breaks(session, rails, walk))
            found.extend(_pending_paid(session, rails, walk))
            found.extend(_rail_missing(session, rails, walk))
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


def _load_quieted_rail_keys(session: Session, walk: _Walk) -> None:
    callback_ids = [sid for typ, sid in walk.quieted if typ == "callback"]
    if callback_ids:
        logs = session.scalars(select(StkCallbackLog).where(StkCallbackLog.id.in_(callback_ids)))
        for row in logs:
            walk.checkouts.add(row.checkout_request_id)
    topup_ids = [sid for typ, sid in walk.quieted if typ == "topup"]
    if topup_ids:
        topups = session.scalars(select(Topup).where(Topup.id.in_(topup_ids)))
        for topup in topups:
            if topup.checkout_request_id:
                walk.checkouts.add(topup.checkout_request_id)
            if topup.mpesa_receipt_number:
                walk.receipts.add(topup.mpesa_receipt_number)


def _callback_breaks(session: Session, walk: _Walk) -> list[ReconBreak]:
    rows = session.scalars(
        select(StkCallbackLog).where(
            StkCallbackLog.disposition.in_(
                (CallbackDisposition.AMOUNT_MISMATCH.value, CallbackDisposition.UNMATCHED.value)
            )
        )
    ).all()
    found: list[ReconBreak] = []
    for row in rows:
        if ("callback", row.id) in walk.quieted:
            continue
        walk.checkouts.add(row.checkout_request_id)
        if row.disposition == CallbackDisposition.AMOUNT_MISMATCH.value:
            found.append(
                _break(
                    walk.run_id,
                    BreakKind.AMOUNT_MISMATCH,
                    "callback",
                    row.id,
                    f"STK callback {row.checkout_request_id} amount did not match the top-up",
                )
            )
        else:
            found.append(
                _break(
                    walk.run_id,
                    BreakKind.MISSING_ON_LEDGER,
                    "callback",
                    row.id,
                    f"STK callback {row.checkout_request_id} matched no top-up",
                )
            )
    return found


def _expired_holds(session: Session, walk: _Walk) -> list[ReconBreak]:
    rows = session.scalars(
        select(Cashout).where(
            Cashout.status == CashoutStatus.EXPIRED.value,
            Cashout.release_journal_entry_id.is_(None),
        )
    ).all()
    return [
        _break(
            walk.run_id,
            BreakKind.IN_FLIGHT_HOLD,
            "cashout",
            row.id,
            "expired cash-out still held in clearing until a late result or suspense",
            our_cents=row.amount_cents,
        )
        for row in rows
        if ("cashout", row.id) not in walk.quieted
    ]


def _settlement_breaks(session: Session, rails: Rails, walk: _Walk) -> list[ReconBreak]:
    topups = session.scalars(select(Topup).where(Topup.checkout_request_id.is_not(None))).all()
    by_checkout = {row.checkout_request_id: row for row in topups if row.checkout_request_id}
    by_receipt = {
        row.mpesa_receipt_number: row for row in topups if row.mpesa_receipt_number is not None
    }
    found: list[ReconBreak] = []
    for provider in rails.providers():
        for row in _list_settlement(provider):
            if _settlement_already_seen(row, walk):
                continue
            topup = None
            if row.checkout_request_id:
                topup = by_checkout.get(row.checkout_request_id)
            if topup is None:
                topup = by_receipt.get(row.receipt_number)
            if topup is not None and topup.status == TopupStatus.SUCCEEDED.value:
                if topup.amount_cents == row.amount_cents:
                    _mark_settlement(row, walk)
                    continue
                if ("topup", topup.id) in walk.quieted:
                    _mark_settlement(row, walk)
                    continue
                _mark_settlement(row, walk)
                found.append(
                    _break(
                        walk.run_id,
                        BreakKind.AMOUNT_MISMATCH,
                        "topup",
                        topup.id,
                        (
                            f"settlement {row.receipt_number} is {row.amount_cents} cents "
                            f"but ledger credited {topup.amount_cents}"
                        ),
                        our_cents=topup.amount_cents,
                        their_cents=row.amount_cents,
                    )
                )
                continue
            subject_type, subject_id = _settlement_subject(topup, row)
            if (subject_type, subject_id) in walk.quieted:
                _mark_settlement(row, walk)
                continue
            _mark_settlement(row, walk)
            detail = (
                f"settlement {row.receipt_number} paid {row.amount_cents} cents"
                if topup is None
                else (
                    f"settlement {row.receipt_number} paid but top-up {topup.id} is {topup.status}"
                )
            )
            if row.checkout_request_id and not row.callback_delivered:
                detail = (
                    f"rail paid {row.checkout_request_id} ({row.receipt_number}) "
                    "but never called back"
                )
            found.append(
                _break(
                    walk.run_id,
                    BreakKind.MISSING_ON_LEDGER,
                    subject_type,
                    subject_id,
                    detail,
                    our_cents=topup.amount_cents if topup is not None else 0,
                    their_cents=row.amount_cents,
                )
            )
    return found


def _pending_paid(session: Session, rails: Rails, walk: _Walk) -> list[ReconBreak]:
    rows = session.scalars(
        select(Topup).where(
            Topup.status != TopupStatus.SUCCEEDED.value,
            Topup.checkout_request_id.is_not(None),
        )
    ).all()
    found: list[ReconBreak] = []
    for topup in rows:
        if ("topup", topup.id) in walk.quieted:
            continue
        assert topup.checkout_request_id is not None
        if topup.checkout_request_id in walk.checkouts:
            continue
        provider = rails.for_topup(topup.provider)
        if provider is None:
            continue
        try:
            queried = provider.stk_query(topup.checkout_request_id)
        except (ProviderError, RailUnavailable, OSError):
            continue
        if queried.processing or queried.outcome is not Outcome.SUCCESS:
            continue
        walk.checkouts.add(topup.checkout_request_id)
        found.append(
            _break(
                walk.run_id,
                BreakKind.MISSING_ON_LEDGER,
                "topup",
                topup.id,
                (
                    f"STK Query says {topup.checkout_request_id} is paid "
                    f"but the top-up is {topup.status}"
                ),
                our_cents=0,
                their_cents=topup.amount_cents,
            )
        )
    return found


def _rail_missing(session: Session, rails: Rails, walk: _Walk) -> list[ReconBreak]:
    rows = session.scalars(
        select(Topup).where(
            Topup.status == TopupStatus.SUCCEEDED.value,
            Topup.checkout_request_id.is_not(None),
        )
    ).all()
    found: list[ReconBreak] = []
    for topup in rows:
        if ("topup", topup.id) in walk.quieted:
            continue
        assert topup.checkout_request_id is not None
        provider = rails.for_topup(topup.provider)
        if provider is None:
            found.append(
                _break(
                    walk.run_id,
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
                    walk.run_id,
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
                walk.run_id,
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


def _list_settlement(provider: PaymentsProvider) -> list[SettlementRow]:
    lister = getattr(provider, "list_settlement", None)
    if not callable(lister):
        return []
    try:
        rows = lister()
    except (ProviderError, RailUnavailable, OSError):
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, SettlementRow)]


def _settlement_already_seen(row: SettlementRow, walk: _Walk) -> bool:
    if row.checkout_request_id and row.checkout_request_id in walk.checkouts:
        return True
    return row.receipt_number in walk.receipts


def _mark_settlement(row: SettlementRow, walk: _Walk) -> None:
    if row.checkout_request_id:
        walk.checkouts.add(row.checkout_request_id)
    walk.receipts.add(row.receipt_number)


def _settlement_subject(topup: Topup | None, row: SettlementRow) -> tuple[str, UUID]:
    if topup is not None:
        return "topup", topup.id
    return "settlement", uuid5(_SETTLEMENT_NS, row.receipt_number)


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
