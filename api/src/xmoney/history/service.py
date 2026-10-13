"""Wallet history, newest first, one item per journal entry that touched the wallet.

Pages are keyset-paginated on (created_at, journal_entry_id), which is unique
per item and covered by ix_postings_account_history. Entries posted after a
page was read sort ahead of its cursor, so later pages neither repeat nor skip
items. Postings are stamped with their transaction's start time, so an entry
whose transaction began before a page was read but committed after it can sort
behind that page's cursor; it appears when the client refreshes from the top.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.orm import Session, aliased

from xmoney.errors import InvalidCursor
from xmoney.identity.models import User
from xmoney.ledger.models import Posting
from xmoney.payments.models import Topup
from xmoney.transfers.models import Transfer

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class ItemKind(StrEnum):
    TOPUP = "topup"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    OTHER = "other"


@dataclass(frozen=True)
class HistoryItem:
    entry_id: UUID
    kind: ItemKind
    amount_cents: int
    counterparty: str | None
    note: str | None
    mpesa_receipt: str | None
    created_at: datetime


@dataclass(frozen=True)
class HistoryPage:
    items: list[HistoryItem]
    next_cursor: str | None


def encode_cursor(created_at: datetime, entry_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{entry_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, entry_id = raw.split("|")
        created_at = datetime.fromisoformat(stamp)
        parsed_id = UUID(entry_id)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursor("cursor is not one this API issued") from exc
    if created_at.tzinfo is None:
        raise InvalidCursor("cursor is not one this API issued")
    return created_at, parsed_id


def wallet_history(
    session: Session,
    *,
    user_id: UUID,
    wallet_account_id: UUID,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> HistoryPage:
    """Wallets are credit-normal, so credits are money in and debits money out."""
    signed = func.sum(
        case((Posting.direction == "credit", Posting.amount_cents), else_=-Posting.amount_cents)
    )
    query = (
        select(Posting.created_at, Posting.journal_entry_id, signed)
        .where(Posting.account_id == wallet_account_id)
        .group_by(Posting.created_at, Posting.journal_entry_id)
        .order_by(Posting.created_at.desc(), Posting.journal_entry_id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        after = decode_cursor(cursor)
        query = query.where(tuple_(Posting.created_at, Posting.journal_entry_id) < tuple_(*after))
    rows = session.execute(query).all()
    more = len(rows) > limit
    rows = rows[:limit]

    entry_ids = [row[1] for row in rows]
    transfers = _transfers_by_entry(session, entry_ids)
    receipts = _topup_receipts_by_entry(session, entry_ids)

    items: list[HistoryItem] = []
    for created_at, entry_id, amount in rows:
        kind, counterparty, note, receipt = ItemKind.OTHER, None, None, None
        if entry_id in transfers:
            sender_id, sender, recipient, note = transfers[entry_id]
            if sender_id == user_id:
                kind, counterparty = ItemKind.TRANSFER_OUT, recipient
            else:
                kind, counterparty = ItemKind.TRANSFER_IN, sender
        elif entry_id in receipts:
            kind, receipt = ItemKind.TOPUP, receipts[entry_id]
        items.append(
            HistoryItem(
                entry_id=entry_id,
                kind=kind,
                amount_cents=int(amount),
                counterparty=counterparty,
                note=note,
                mpesa_receipt=receipt,
                created_at=created_at,
            )
        )
    last = items[-1] if more else None
    next_cursor = encode_cursor(last.created_at, last.entry_id) if last else None
    return HistoryPage(items=items, next_cursor=next_cursor)


def _transfers_by_entry(
    session: Session, entry_ids: list[UUID]
) -> dict[UUID, tuple[UUID, str, str, str | None]]:
    if not entry_ids:
        return {}
    sender = aliased(User)
    recipient = aliased(User)
    rows = session.execute(
        select(
            Transfer.journal_entry_id,
            Transfer.sender_user_id,
            sender.handle,
            recipient.handle,
            Transfer.note,
        )
        .join(sender, sender.id == Transfer.sender_user_id)
        .join(recipient, recipient.id == Transfer.recipient_user_id)
        .where(Transfer.journal_entry_id.in_(entry_ids))
    ).all()
    return {row[0]: (row[1], row[2], row[3], row[4]) for row in rows}


def _topup_receipts_by_entry(session: Session, entry_ids: list[UUID]) -> dict[UUID, str | None]:
    if not entry_ids:
        return {}
    rows = session.execute(
        select(Topup.journal_entry_id, Topup.mpesa_receipt_number).where(
            Topup.journal_entry_id.in_(entry_ids)
        )
    ).all()
    return {row[0]: row[1] for row in rows if row[0] is not None}
