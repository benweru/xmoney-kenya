"""B2C cash-outs: hold the wallet, enqueue the rail call, settle or release later.

POST /v1/cashouts locks the wallet, posts the hold (debit wallet, credit
`system:mpesa_clearing`), and writes a `b2c.payment` outbox job in one
transaction. The worker calls Daraja. A success result settles clearing into
`system:mpesa_float`. A failure releases the hold. A timeout expires the
row and leaves the hold — money may still move on the rail.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xmoney.config import get_settings
from xmoney.db import release_read_transaction
from xmoney.errors import (
    CashoutNotFound,
    IdempotencyConflict,
    InsufficientFunds,
    InvalidAmount,
    LedgerError,
)
from xmoney.identity.validators import normalize_phone
from xmoney.ledger.money import (
    Direction,
    PostCommand,
    PostingLine,
    require_cents,
    require_idempotency_key,
)
from xmoney.ledger.service import get_balance, lock_accounts, post_entry_in_transaction
from xmoney.ledger.system import MPESA_CLEARING, MPESA_FLOAT
from xmoney.payments.cashout_state import FINAL, transition
from xmoney.payments.daraja import parse_b2c_result
from xmoney.payments.models import B2cCallbackLog, CallbackDisposition, Cashout, CashoutStatus
from xmoney.payments.provider import B2cAccepted, B2cResult, PaymentsProvider

logger = logging.getLogger("xmoney.cashouts")

_UNIQUE_VIOLATION = "23505"


@dataclass(frozen=True)
class CashoutView:
    id: UUID
    status: CashoutStatus
    rail: str
    amount_cents: int
    phone_e164: str
    conversation_id: str | None
    mpesa_receipt_number: str | None
    result_code: int | None
    result_desc: str | None
    created_at: datetime
    resolved_at: datetime | None
    idempotent_replay: bool = False


def result_url(rail: str | None = None) -> str:
    return _callback_url("result", rail)


def timeout_url(rail: str | None = None) -> str:
    return _callback_url("timeout", rail)


def _callback_url(kind: str, rail: str | None) -> str:
    settings = get_settings()
    base = settings.public_base_url
    if rail == "mock" and settings.daraja_mock_callback_base_url:
        base = settings.daraja_mock_callback_base_url
    return base.rstrip("/") + f"/v1/payments/b2c/{kind}/" + settings.stk_callback_token


def start_cashout(
    session: Session,
    provider: PaymentsProvider,
    *,
    user_id: UUID,
    wallet_account_id: UUID,
    phone: str,
    amount_cents: int,
    idempotency_key: str,
    now: datetime | None = None,
) -> CashoutView:
    """Hold funds and enqueue B2C. Replaying the key returns the same cash-out."""
    amount = _require_cashout_amount(amount_cents)
    key = require_idempotency_key(idempotency_key)
    phone_e164 = normalize_phone(phone)
    digest = _request_hash(amount, phone_e164)
    now = now or datetime.now(UTC)
    cashout, created = _create_or_replay(
        session,
        user_id=user_id,
        wallet_account_id=wallet_account_id,
        key=key,
        digest=digest,
        amount=amount,
        phone=phone_e164,
        provider_name=provider.name,
        now=now,
    )
    return _view(cashout, replay=not created)


def handle_b2c_callback(
    session: Session,
    provider: PaymentsProvider,
    payload: Mapping[str, Any],
    *,
    timed_out: bool,
    now: datetime | None = None,
) -> CallbackDisposition:
    """Apply a B2C result or timeout. Timeouts expire; they do not refund."""
    result = provider.parse_b2c_result(payload)
    if timed_out:
        result = B2cResult(
            originator_conversation_id=result.originator_conversation_id,
            conversation_id=result.conversation_id,
            result_code=result.result_code,
            result_desc=result.result_desc,
            outcome=result.outcome,
            amount_cents=result.amount_cents,
            transaction_id=result.transaction_id,
            timed_out=True,
        )
    now = now or datetime.now(UTC)
    release_read_transaction(session)
    cashout_id: UUID | None = None
    with session.begin():
        cashout = _lock_matching(session, result)
        disposition = (
            _apply(session, cashout, result, now)
            if cashout is not None
            else CallbackDisposition.UNMATCHED
        )
        if cashout is not None:
            cashout_id = cashout.id
        session.add(
            B2cCallbackLog(
                id=uuid4(),
                originator_conversation_id=result.originator_conversation_id,
                conversation_id=result.conversation_id,
                cashout_id=cashout_id,
                result_code=result.result_code,
                timed_out=result.timed_out,
                disposition=disposition.value,
                payload=dict(payload),
            )
        )
    if disposition is CallbackDisposition.UNMATCHED:
        logger.warning(
            "B2C callback for unknown OriginatorConversationID %s",
            result.originator_conversation_id,
        )
    return disposition


def get_cashout(
    session: Session,
    *,
    cashout_id: UUID,
    user_id: UUID,
    now: datetime | None = None,
) -> CashoutView:
    cashout = session.get(Cashout, cashout_id)
    if cashout is None or cashout.user_id != user_id:
        raise CashoutNotFound("no such cash-out")
    return _view(resolve_cashout(session, cashout_id, now=now))


def resolve_stale_cashouts(session: Session, now: datetime | None = None) -> int:
    """Fail holds that never reached the rail; expire pending holds we stopped waiting on."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=get_settings().b2c_expire_after_seconds)
    ids = session.scalars(
        select(Cashout.id).where(
            Cashout.status.in_([CashoutStatus.INITIATED.value, CashoutStatus.PENDING.value]),
            Cashout.created_at <= cutoff,
        )
    ).all()
    changed = 0
    for cashout_id in ids:
        before = session.get(Cashout, cashout_id)
        if before is None:
            continue
        status_before = before.status
        after = resolve_cashout(session, cashout_id, now=now)
        changed += int(after.status != status_before)
    return changed


def resolve_cashout(session: Session, cashout_id: UUID, now: datetime | None = None) -> Cashout:
    """Expire or fail a cash-out that has waited too long. No rail call."""
    now = now or datetime.now(UTC)
    cashout = session.get(Cashout, cashout_id, populate_existing=True)
    if cashout is None:
        raise CashoutNotFound("no such cash-out")
    status = CashoutStatus(cashout.status)
    if status in FINAL or status is CashoutStatus.EXPIRED:
        return cashout
    age = now - cashout.created_at
    if age < timedelta(seconds=get_settings().b2c_expire_after_seconds):
        return cashout
    release_read_transaction(session)
    with session.begin():
        locked = session.scalar(select(Cashout).where(Cashout.id == cashout_id).with_for_update())
        assert locked is not None
        locked_status = CashoutStatus(locked.status)
        if locked_status is CashoutStatus.INITIATED:
            locked.result_desc = "M-PESA did not accept the cash-out before it expired"
            _release(session, locked, now, result_code=None)
        elif locked_status is CashoutStatus.PENDING:
            locked.result_desc = "No answer from M-PESA before the cash-out expired"
            transition(locked, CashoutStatus.EXPIRED, now)
    session.refresh(locked)
    return locked


def record_accepted(
    session: Session, cashout_id: UUID, accepted: B2cAccepted, now: datetime
) -> Cashout:
    release_read_transaction(session)
    with session.begin():
        cashout = session.scalar(select(Cashout).where(Cashout.id == cashout_id).with_for_update())
        assert cashout is not None
        if cashout.status == CashoutStatus.INITIATED:
            cashout.conversation_id = accepted.conversation_id
            transition(cashout, CashoutStatus.PENDING, now)
            session.flush()
            _apply_early_callback(session, cashout, now)
    session.refresh(cashout)
    return cashout


def record_refusal(session: Session, cashout_id: UUID, reason: str, now: datetime) -> Cashout:
    release_read_transaction(session)
    with session.begin():
        cashout = session.scalar(select(Cashout).where(Cashout.id == cashout_id).with_for_update())
        assert cashout is not None
        if cashout.status == CashoutStatus.INITIATED:
            cashout.result_desc = reason[:300]
            _release(session, cashout, now, result_code=None)
    session.refresh(cashout)
    return cashout


def _create_or_replay(
    session: Session,
    *,
    user_id: UUID,
    wallet_account_id: UUID,
    key: str,
    digest: str,
    amount: int,
    phone: str,
    provider_name: str,
    now: datetime,
) -> tuple[Cashout, bool]:
    release_read_transaction(session)
    for _ in range(3):
        try:
            with session.begin():
                existing = session.scalar(
                    select(Cashout).where(
                        Cashout.user_id == user_id, Cashout.idempotency_key == key
                    )
                )
                if existing is not None:
                    if existing.request_hash != digest:
                        raise IdempotencyConflict(
                            "Idempotency-Key was already used for a different cash-out"
                        )
                    return existing, False
                lock_accounts(session, (wallet_account_id,))
                available = get_balance(session, wallet_account_id).balance_cents
                if available < amount:
                    raise InsufficientFunds(
                        f"balance is KES {available / 100:,.2f}; "
                        f"cannot cash out KES {amount / 100:,.2f}"
                    )
                cashout_id = uuid4()
                posted = post_entry_in_transaction(
                    session,
                    PostCommand(
                        idempotency_key=f"cashout-hold:{cashout_id}",
                        description=f"Hold for M-PESA cash-out {cashout_id}",
                        postings=(
                            PostingLine(wallet_account_id, Direction.DEBIT, amount),
                            PostingLine(MPESA_CLEARING.id, Direction.CREDIT, amount),
                        ),
                    ),
                )
                cashout = Cashout(
                    id=cashout_id,
                    user_id=user_id,
                    wallet_account_id=wallet_account_id,
                    idempotency_key=key,
                    request_hash=digest,
                    amount_cents=amount,
                    phone_e164=phone,
                    status=CashoutStatus.INITIATED.value,
                    provider=provider_name,
                    originator_conversation_id=cashout_id.hex,
                    hold_journal_entry_id=posted.entry_id,
                    updated_at=now,
                )
                session.add(cashout)
                session.flush()
                from xmoney.payments.jobs import enqueue_b2c_payment

                enqueue_b2c_payment(session, cashout.id, now=now)
            return cashout, True
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) != _UNIQUE_VIOLATION:
                raise
    raise LedgerError("could not create the cash-out after concurrent retries")


def _lock_matching(session: Session, result: B2cResult) -> Cashout | None:
    clauses = [Cashout.originator_conversation_id == result.originator_conversation_id]
    if result.conversation_id:
        clauses.append(Cashout.conversation_id == result.conversation_id)
    return session.scalar(select(Cashout).where(or_(*clauses)).with_for_update())


def _apply_early_callback(session: Session, cashout: Cashout, now: datetime) -> None:
    early = session.scalars(
        select(B2cCallbackLog)
        .where(
            B2cCallbackLog.originator_conversation_id == cashout.originator_conversation_id,
            B2cCallbackLog.disposition == CallbackDisposition.UNMATCHED.value,
        )
        .order_by(B2cCallbackLog.received_at, B2cCallbackLog.id)
        .with_for_update()
    ).all()
    for log in early:
        parsed = parse_b2c_result(log.payload)
        result = B2cResult(
            originator_conversation_id=parsed.originator_conversation_id,
            conversation_id=parsed.conversation_id or cashout.conversation_id,
            result_code=parsed.result_code,
            result_desc=parsed.result_desc,
            outcome=parsed.outcome,
            amount_cents=parsed.amount_cents,
            transaction_id=parsed.transaction_id,
            timed_out=log.timed_out,
        )
        log.cashout_id = cashout.id
        log.disposition = _apply(session, cashout, result, now).value


def _apply(
    session: Session, cashout: Cashout, result: B2cResult, now: datetime
) -> CallbackDisposition:
    status = CashoutStatus(cashout.status)
    if status in FINAL:
        if result.timed_out:
            return CallbackDisposition.DUPLICATE
        if result.succeeded != (status is CashoutStatus.SUCCEEDED):
            return CallbackDisposition.CONFLICT
        if result.transaction_id and cashout.mpesa_receipt_number is None:
            cashout.mpesa_receipt_number = result.transaction_id
        return CallbackDisposition.DUPLICATE
    if result.succeeded and result.amount_cents not in (None, cashout.amount_cents):
        return CallbackDisposition.AMOUNT_MISMATCH
    if status is CashoutStatus.INITIATED and (result.timed_out or result.succeeded):
        return CallbackDisposition.RECORDED
    if result.timed_out:
        if status is CashoutStatus.PENDING:
            cashout.result_code = result.result_code
            cashout.result_desc = (result.result_desc or "B2C timed out")[:300]
            transition(cashout, CashoutStatus.EXPIRED, now)
            return CallbackDisposition.APPLIED
        return CallbackDisposition.DUPLICATE
    cashout.result_code = result.result_code
    cashout.result_desc = result.result_desc[:300]
    if result.succeeded:
        _settle(session, cashout, result, now)
    else:
        _release(session, cashout, now, result_code=result.result_code)
    return CallbackDisposition.APPLIED


def _settle(session: Session, cashout: Cashout, result: B2cResult, now: datetime) -> None:
    posted = post_entry_in_transaction(
        session,
        PostCommand(
            idempotency_key=f"cashout-settle:{cashout.id}",
            description=f"M-PESA B2C cash-out {cashout.conversation_id or cashout.id}",
            external_ref=cashout.conversation_id,
            postings=(
                PostingLine(MPESA_CLEARING.id, Direction.DEBIT, cashout.amount_cents),
                PostingLine(MPESA_FLOAT.id, Direction.CREDIT, cashout.amount_cents),
            ),
        ),
    )
    cashout.settle_journal_entry_id = posted.entry_id
    if result.transaction_id:
        cashout.mpesa_receipt_number = result.transaction_id
    transition(cashout, CashoutStatus.SUCCEEDED, now)


def _release(session: Session, cashout: Cashout, now: datetime, *, result_code: int | None) -> None:
    posted = post_entry_in_transaction(
        session,
        PostCommand(
            idempotency_key=f"cashout-release:{cashout.id}",
            description=f"Release hold for cash-out {cashout.id}",
            postings=(
                PostingLine(MPESA_CLEARING.id, Direction.DEBIT, cashout.amount_cents),
                PostingLine(cashout.wallet_account_id, Direction.CREDIT, cashout.amount_cents),
            ),
        ),
    )
    cashout.release_journal_entry_id = posted.entry_id
    if result_code is not None:
        cashout.result_code = result_code
    transition(cashout, CashoutStatus.FAILED, now)


def _require_cashout_amount(value: object) -> int:
    amount = require_cents(value)
    if amount % 100 != 0:
        raise InvalidAmount("M-PESA cash-outs must be a whole number of shillings")
    cap = min(250_000 * 100, get_settings().topup_max_cents)
    if amount > cap:
        raise InvalidAmount(f"a cash-out cannot exceed KES {cap // 100:,}")
    return amount


def _request_hash(amount: int, phone: str) -> str:
    encoded = json.dumps({"amount_cents": amount, "phone": phone}, sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _view(cashout: Cashout, *, replay: bool = False) -> CashoutView:
    return CashoutView(
        id=cashout.id,
        status=CashoutStatus(cashout.status),
        rail=cashout.provider,
        amount_cents=cashout.amount_cents,
        phone_e164=cashout.phone_e164,
        conversation_id=cashout.conversation_id,
        mpesa_receipt_number=cashout.mpesa_receipt_number,
        result_code=cashout.result_code,
        result_desc=cashout.result_desc,
        created_at=cashout.created_at,
        resolved_at=cashout.resolved_at,
        idempotent_replay=replay,
    )
