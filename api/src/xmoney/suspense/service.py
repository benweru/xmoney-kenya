"""Park unmatched inbound value, then apply it to a wallet or return it to the float.

Opening always posts debit `system:mpesa_float`, credit `system:suspense`: we
recorded cash we cannot yet name. Applying posts debit suspense, credit the
wallet. Refunding posts debit suspense, credit float. HTTP apply/refund is
staff-session only and off on a public https demo (ADR 019). Opening stays CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from xmoney.db import release_read_transaction
from xmoney.errors import InvalidSuspense, SuspenseNotFound
from xmoney.identity.service import lookup_handle
from xmoney.ledger.money import Direction, PostCommand, PostingLine, require_cents
from xmoney.ledger.service import lock_accounts, post_entry_in_transaction
from xmoney.ledger.system import MPESA_FLOAT, SUSPENSE
from xmoney.recon.models import ReconBreak
from xmoney.suspense.models import SuspenseItem, SuspenseStatus


@dataclass(frozen=True)
class SuspenseView:
    id: UUID
    amount_cents: int
    status: str
    open_reason: str
    resolve_reason: str | None
    recon_break_id: UUID | None
    wallet_account_id: UUID | None
    created_at: datetime | None
    resolved_at: datetime | None


def _reason(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > 500:
        raise InvalidSuspense("reason must be 1-500 characters")
    return cleaned


def _actor(value: str) -> str:
    cleaned = value.strip().lstrip("@").lower()
    if not cleaned or len(cleaned) > 40:
        raise InvalidSuspense("actor must be 1-40 characters")
    return cleaned


def open_suspense(
    session: Session,
    *,
    amount_cents: int,
    reason: str,
    recon_break_id: UUID | None = None,
) -> SuspenseView:
    amount = require_cents(amount_cents)
    note = _reason(reason)
    release_read_transaction(session)
    with session.begin():
        if recon_break_id is not None:
            brk = session.get(ReconBreak, recon_break_id)
            if brk is None:
                raise InvalidSuspense("unknown recon break")
            existing = session.scalar(
                select(SuspenseItem.id).where(
                    SuspenseItem.recon_break_id == recon_break_id,
                    SuspenseItem.status == SuspenseStatus.OPEN.value,
                )
            )
            if existing is not None:
                raise InvalidSuspense("that break already has an open suspense item")
        item_id = uuid4()
        posted = post_entry_in_transaction(
            session,
            PostCommand(
                idempotency_key=f"suspense-open:{item_id}",
                description=f"Suspense open: {note}"[:500],
                postings=(
                    PostingLine(MPESA_FLOAT.id, Direction.DEBIT, amount),
                    PostingLine(SUSPENSE.id, Direction.CREDIT, amount),
                ),
            ),
        )
        item = SuspenseItem(
            id=item_id,
            recon_break_id=recon_break_id,
            amount_cents=amount,
            status=SuspenseStatus.OPEN.value,
            open_reason=note,
            open_journal_entry_id=posted.entry_id,
        )
        session.add(item)
        session.flush()
        return _view(item)


def apply_to_wallet(
    session: Session,
    *,
    item_id: UUID,
    handle: str,
    reason: str,
    actor: str = "cli",
) -> SuspenseView:
    note = _reason(reason)
    who = _actor(actor)
    recipient = lookup_handle(session, handle)
    release_read_transaction(session)
    with session.begin():
        item = _lock_open(session, item_id)
        lock_accounts(session, (recipient.wallet_account_id,))
        posted = post_entry_in_transaction(
            session,
            PostCommand(
                idempotency_key=f"suspense-apply:{item.id}",
                description=f"Suspense to @{recipient.handle} by @{who}: {note}"[:500],
                postings=(
                    PostingLine(SUSPENSE.id, Direction.DEBIT, item.amount_cents),
                    PostingLine(recipient.wallet_account_id, Direction.CREDIT, item.amount_cents),
                ),
            ),
        )
        item.status = SuspenseStatus.APPLIED.value
        item.resolve_reason = note
        item.resolve_journal_entry_id = posted.entry_id
        item.wallet_account_id = recipient.wallet_account_id
        item.resolved_at = datetime.now(UTC)
        _quiet_linked_break(session, item)
        session.flush()
        return _view(item)


def refund_to_float(
    session: Session, *, item_id: UUID, reason: str, actor: str = "cli"
) -> SuspenseView:
    note = _reason(reason)
    who = _actor(actor)
    release_read_transaction(session)
    with session.begin():
        item = _lock_open(session, item_id)
        posted = post_entry_in_transaction(
            session,
            PostCommand(
                idempotency_key=f"suspense-refund:{item.id}",
                description=f"Suspense refund by @{who}: {note}"[:500],
                postings=(
                    PostingLine(SUSPENSE.id, Direction.DEBIT, item.amount_cents),
                    PostingLine(MPESA_FLOAT.id, Direction.CREDIT, item.amount_cents),
                ),
            ),
        )
        item.status = SuspenseStatus.REFUNDED.value
        item.resolve_reason = note
        item.resolve_journal_entry_id = posted.entry_id
        item.resolved_at = datetime.now(UTC)
        _quiet_linked_break(session, item)
        session.flush()
        return _view(item)


def _quiet_linked_break(session: Session, item: SuspenseItem) -> None:
    if item.recon_break_id is None:
        return
    linked = session.get(ReconBreak, item.recon_break_id)
    if linked is None:
        return
    now = datetime.now(UTC)
    query = select(ReconBreak).where(ReconBreak.quieted_at.is_(None))
    if linked.subject_id is None:
        query = query.where(ReconBreak.id == linked.id)
    else:
        query = query.where(
            ReconBreak.subject_type == linked.subject_type,
            ReconBreak.subject_id == linked.subject_id,
        )
    for brk in session.scalars(query):
        brk.quieted_at = now


def _lock_open(session: Session, item_id: UUID) -> SuspenseItem:
    item = session.scalar(select(SuspenseItem).where(SuspenseItem.id == item_id).with_for_update())
    if item is None:
        raise SuspenseNotFound(f"unknown suspense item {item_id}")
    if item.status != SuspenseStatus.OPEN.value:
        raise InvalidSuspense(f"suspense item is {item.status}")
    return item


def _view(item: SuspenseItem) -> SuspenseView:
    return SuspenseView(
        id=item.id,
        amount_cents=item.amount_cents,
        status=item.status,
        open_reason=item.open_reason,
        resolve_reason=item.resolve_reason,
        recon_break_id=item.recon_break_id,
        wallet_account_id=item.wallet_account_id,
        created_at=item.created_at,
        resolved_at=item.resolved_at,
    )
