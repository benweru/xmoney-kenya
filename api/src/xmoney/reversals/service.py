"""Full reversals as new journal entries. The original entry is never edited.

Amounts at or above `reversal_maker_checker_cents` stay proposed until a
different actor approves. Smaller ones post immediately. There is no HTTP route.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from xmoney.config import get_settings
from xmoney.db import release_read_transaction
from xmoney.errors import InsufficientFunds, InvalidReversal, ReversalNotFound
from xmoney.ledger.models import JournalEntry, NormalSide, Posting
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import get_balance, lock_accounts, post_entry_in_transaction
from xmoney.reversals.models import Reversal, ReversalStatus

_ACTOR_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


@dataclass(frozen=True)
class ReversalView:
    id: UUID
    original_journal_entry_id: UUID
    amount_cents: int
    status: str
    reason: str
    maker: str
    checker: str | None
    needs_checker: bool


def _actor(value: str) -> str:
    name = value.strip()
    if _ACTOR_RE.fullmatch(name) is None:
        raise InvalidReversal("actor must be 1-40 characters from [A-Za-z0-9._-]")
    return name


def _reason(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > 500:
        raise InvalidReversal("reason must be 1-500 characters")
    return cleaned


def propose_reversal(
    session: Session,
    *,
    original_journal_entry_id: UUID,
    reason: str,
    maker: str,
) -> ReversalView:
    note = _reason(reason)
    actor = _actor(maker)
    release_read_transaction(session)
    with session.begin():
        original, lines, amount = _original(session, original_journal_entry_id)
        _assert_no_active(session, original.id)
        item = Reversal(
            id=uuid4(),
            original_journal_entry_id=original.id,
            amount_cents=amount,
            status=ReversalStatus.PROPOSED.value,
            reason=note,
            maker=actor,
        )
        session.add(item)
        session.flush()
        if amount >= get_settings().reversal_maker_checker_cents:
            return _view(item, needs_checker=True)
        _post(session, item, lines, checker=None)
        return _view(item, needs_checker=False)


def approve_reversal(session: Session, *, reversal_id: UUID, checker: str) -> ReversalView:
    actor = _actor(checker)
    release_read_transaction(session)
    with session.begin():
        item = _lock(session, reversal_id)
        if item.status != ReversalStatus.PROPOSED.value:
            raise InvalidReversal(f"reversal is {item.status}")
        if actor == item.maker:
            raise InvalidReversal("the maker cannot approve their own reversal")
        _entry, lines, _amount = _original(session, item.original_journal_entry_id)
        _post(session, item, lines, checker=actor)
        return _view(item, needs_checker=False)


def reject_reversal(
    session: Session, *, reversal_id: UUID, checker: str, reason: str
) -> ReversalView:
    actor = _actor(checker)
    note = _reason(reason)
    release_read_transaction(session)
    with session.begin():
        item = _lock(session, reversal_id)
        if item.status != ReversalStatus.PROPOSED.value:
            raise InvalidReversal(f"reversal is {item.status}")
        if actor == item.maker:
            raise InvalidReversal("the maker cannot reject their own reversal")
        item.status = ReversalStatus.REJECTED.value
        item.checker = actor
        item.decision_reason = note
        item.decided_at = datetime.now(UTC)
        session.flush()
        return _view(item, needs_checker=False)


def _original(session: Session, entry_id: UUID) -> tuple[JournalEntry, list[Posting], int]:
    original = session.get(JournalEntry, entry_id)
    if original is None:
        raise InvalidReversal("unknown journal entry")
    lines = session.scalars(
        select(Posting).where(Posting.journal_entry_id == original.id).order_by(Posting.line_no)
    ).all()
    if len(lines) < 2:
        raise InvalidReversal("journal entry has no postings to reverse")
    amount = sum(line.amount_cents for line in lines if line.direction == "debit")
    return original, list(lines), amount


def _assert_no_active(session: Session, original_id: UUID) -> None:
    existing = session.scalar(
        select(Reversal.id).where(
            Reversal.original_journal_entry_id == original_id,
            Reversal.status.in_((ReversalStatus.PROPOSED.value, ReversalStatus.POSTED.value)),
        )
    )
    if existing is not None:
        raise InvalidReversal("that journal entry already has a proposed or posted reversal")


def _lock(session: Session, reversal_id: UUID) -> Reversal:
    item = session.scalar(select(Reversal).where(Reversal.id == reversal_id).with_for_update())
    if item is None:
        raise ReversalNotFound(f"unknown reversal {reversal_id}")
    return item


def _post(
    session: Session,
    item: Reversal,
    original_lines: list[Posting],
    *,
    checker: str | None,
) -> None:
    flipped = tuple(
        PostingLine(
            line.account_id,
            Direction.CREDIT if line.direction == "debit" else Direction.DEBIT,
            line.amount_cents,
        )
        for line in original_lines
    )
    lock_accounts(session, (line.account_id for line in flipped))
    _refuse_overdraft(session, flipped)
    posted = post_entry_in_transaction(
        session,
        PostCommand(
            idempotency_key=f"reverse:{item.id}",
            description=f"Reversal of {item.original_journal_entry_id}: {item.reason}"[:500],
            postings=flipped,
        ),
    )
    item.status = ReversalStatus.POSTED.value
    item.checker = checker
    item.reversal_journal_entry_id = posted.entry_id
    item.decided_at = datetime.now(UTC)
    session.flush()


def _refuse_overdraft(session: Session, lines: tuple[PostingLine, ...]) -> None:
    accounts = {row.id: row for row in lock_accounts(session, (line.account_id for line in lines))}
    for line in lines:
        account = accounts[line.account_id]
        if account.allow_negative:
            continue
        available = get_balance(session, account.id).balance_cents
        reduces = (
            line.direction is Direction.DEBIT and account.normal_side == NormalSide.CREDIT.value
        ) or (line.direction is Direction.CREDIT and account.normal_side == NormalSide.DEBIT.value)
        if reduces and available < line.amount_cents:
            raise InsufficientFunds(
                f"balance is KES {available / 100:,.2f}; "
                f"cannot reverse KES {line.amount_cents / 100:,.2f} on {account.code}"
            )


def _view(item: Reversal, *, needs_checker: bool) -> ReversalView:
    return ReversalView(
        id=item.id,
        original_journal_entry_id=item.original_journal_entry_id,
        amount_cents=item.amount_cents,
        status=item.status,
        reason=item.reason,
        maker=item.maker,
        checker=item.checker,
        needs_checker=needs_checker,
    )
