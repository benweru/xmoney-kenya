"""Send money to an @handle. Never overdraws, even under concurrent sends.

Both wallets are locked in account-id order before the sender's balance is
read, and the journal entry and the transfer row commit in that same
transaction. Two sends from one wallet therefore check the balance one after
the other, and A -> B racing B -> A cannot deadlock. A refused send leaves no
row, so retrying its key after a top-up is re-evaluated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xmoney.db import release_read_transaction
from xmoney.errors import (
    IdempotencyConflict,
    InsufficientFunds,
    InvalidTransfer,
    LedgerError,
)
from xmoney.identity.service import lookup_handle
from xmoney.ledger.money import (
    Direction,
    PostCommand,
    PostingLine,
    require_cents,
    require_idempotency_key,
)
from xmoney.ledger.service import get_balance, lock_accounts, post_entry_in_transaction
from xmoney.ledger.system import FEES
from xmoney.transfers.fees import FeeQuote, quote_p2p
from xmoney.transfers.models import Transfer

_UNIQUE_VIOLATION = "23505"
_MAX_NOTE = 140


@dataclass(frozen=True)
class TransferView:
    id: UUID
    sender_handle: str
    recipient_handle: str
    amount_cents: int
    fee_cents: int
    fee_schedule_version: int
    note: str | None
    created_at: datetime
    idempotent_replay: bool


def send(
    session: Session,
    *,
    sender_user_id: UUID,
    sender_handle: str,
    sender_wallet_id: UUID,
    to_handle: str,
    amount_cents: int,
    idempotency_key: str,
    note: str | None = None,
) -> TransferView:
    amount = require_cents(amount_cents)
    key = require_idempotency_key(idempotency_key)
    clean_note = _clean_note(note)
    recipient = lookup_handle(session, to_handle)
    if recipient.user_id == sender_user_id:
        raise InvalidTransfer("you cannot send money to yourself")
    digest = _request_hash(recipient.user_id, amount, clean_note)
    release_read_transaction(session)

    for _ in range(3):
        try:
            with session.begin():
                existing = session.scalar(
                    select(Transfer).where(
                        Transfer.sender_user_id == sender_user_id,
                        Transfer.idempotency_key == key,
                    )
                )
                if existing is not None:
                    if existing.request_hash != digest:
                        raise IdempotencyConflict(
                            "Idempotency-Key was already used for a different transfer"
                        )
                    return _view(existing, sender_handle, recipient.handle, replay=True)

                lock_accounts(session, (sender_wallet_id, recipient.wallet_account_id))
                quote = quote_p2p(session, sender_user_id=sender_user_id, amount_cents=amount)
                available = get_balance(session, sender_wallet_id).balance_cents
                if available < quote.total_cents:
                    raise InsufficientFunds(_funds_message(available, quote))
                transfer_id = uuid4()
                posted = post_entry_in_transaction(
                    session,
                    PostCommand(
                        idempotency_key=f"transfer:{transfer_id}",
                        description=f"Transfer @{sender_handle} to @{recipient.handle}",
                        postings=_postings(
                            sender_wallet_id,
                            recipient.wallet_account_id,
                            quote.amount_cents,
                            quote.fee_cents,
                        ),
                    ),
                )
                transfer = Transfer(
                    id=transfer_id,
                    sender_user_id=sender_user_id,
                    recipient_user_id=recipient.user_id,
                    amount_cents=quote.amount_cents,
                    fee_cents=quote.fee_cents,
                    fee_schedule_id=quote.schedule_id,
                    fee_schedule_version=quote.schedule_version,
                    note=clean_note,
                    idempotency_key=key,
                    request_hash=digest,
                    journal_entry_id=posted.entry_id,
                )
                session.add(transfer)
                session.flush()
                return _view(transfer, sender_handle, recipient.handle, replay=False)
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) != _UNIQUE_VIOLATION:
                raise
    raise LedgerError("could not record the transfer after concurrent retries")


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    cleaned = " ".join(note.split())
    if len(cleaned) > _MAX_NOTE:
        raise InvalidTransfer(f"note must be at most {_MAX_NOTE} characters")
    return cleaned or None


def _postings(
    sender_wallet_id: UUID, recipient_wallet_id: UUID, amount: int, fee: int
) -> tuple[PostingLine, ...]:
    lines = [
        PostingLine(sender_wallet_id, Direction.DEBIT, amount + fee),
        PostingLine(recipient_wallet_id, Direction.CREDIT, amount),
    ]
    if fee:
        lines.append(PostingLine(FEES.id, Direction.CREDIT, fee))
    return tuple(lines)


def _funds_message(available: int, quote: FeeQuote) -> str:
    if quote.fee_cents == 0:
        return (
            f"balance is KES {available / 100:,.2f}; "
            f"cannot send KES {quote.amount_cents / 100:,.2f}"
        )
    return (
        f"balance is KES {available / 100:,.2f}; "
        f"cannot send KES {quote.amount_cents / 100:,.2f} "
        f"plus KES {quote.fee_cents / 100:,.2f} fee"
    )


def _request_hash(recipient_user_id: UUID, amount: int, note: str | None) -> str:
    payload = {"amount_cents": amount, "note": note, "recipient": str(recipient_user_id)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _view(transfer: Transfer, sender: str, recipient: str, *, replay: bool) -> TransferView:
    return TransferView(
        id=transfer.id,
        sender_handle=sender,
        recipient_handle=recipient,
        amount_cents=transfer.amount_cents,
        fee_cents=transfer.fee_cents,
        fee_schedule_version=transfer.fee_schedule_version,
        note=transfer.note,
        created_at=transfer.created_at,
        idempotent_replay=replay,
    )
