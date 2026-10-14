"""STK Push top-ups: start, apply callbacks exactly once, and resolve silent pushes.

Rail calls never run inside a database transaction. Each state change locks
the top-up row, so a callback, a duplicate of it, and an STK Query answer are
applied one at a time and only the first final answer moves money. The wallet
credit is posted in the same transaction as the status change.
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

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xmoney.config import get_settings
from xmoney.db import release_read_transaction
from xmoney.errors import (
    IdempotencyConflict,
    InvalidAmount,
    LedgerError,
    ProviderError,
    TopupNotFound,
)
from xmoney.identity.validators import normalize_phone
from xmoney.ledger.money import (
    Direction,
    PostCommand,
    PostingLine,
    require_cents,
    require_idempotency_key,
)
from xmoney.ledger.service import post_entry_in_transaction
from xmoney.ledger.system import MPESA_FLOAT
from xmoney.payments.daraja import parse_stk_callback
from xmoney.payments.deps import Rails
from xmoney.payments.models import CallbackDisposition, StkCallbackLog, Topup, TopupStatus
from xmoney.payments.provider import PaymentsProvider, StkPushAccepted, StkPushRequest
from xmoney.payments.state import FINAL, transition

logger = logging.getLogger("xmoney.topups")

MAX_TOPUP_CENTS = 250_000 * 100
_UNIQUE_VIOLATION = "23505"
_ACCOUNT_REFERENCE = "XMONEY"
_DESCRIPTION = "Wallet topup"


@dataclass(frozen=True)
class TopupView:
    id: UUID
    status: TopupStatus
    rail: str
    amount_cents: int
    phone_e164: str
    checkout_request_id: str | None
    mpesa_receipt_number: str | None
    result_code: int | None
    result_desc: str | None
    created_at: datetime
    resolved_at: datetime | None
    idempotent_replay: bool = False


@dataclass(frozen=True)
class RailResult:
    """A final answer from a callback or STK Query, in one shape."""

    result_code: int
    result_desc: str
    amount_cents: int | None = None
    receipt: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.result_code == 0


def callback_url(rail: str | None = None) -> str:
    settings = get_settings()
    base = settings.public_base_url
    if rail == "mock" and settings.daraja_mock_callback_base_url:
        base = settings.daraja_mock_callback_base_url
    return base.rstrip("/") + "/v1/payments/stk/callback/" + settings.stk_callback_token


def start_topup(
    session: Session,
    provider: PaymentsProvider,
    *,
    user_id: UUID,
    wallet_account_id: UUID,
    phone: str,
    amount_cents: int,
    idempotency_key: str,
    now: datetime | None = None,
) -> TopupView:
    """Create the top-up and send the STK Push. Replaying the key returns the same top-up."""
    amount = _require_topup_amount(amount_cents)
    key = require_idempotency_key(idempotency_key)
    phone_e164 = normalize_phone(phone)
    digest = _request_hash(amount, phone_e164)
    now = now or datetime.now(UTC)

    topup, created = _create_or_replay(
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
    if topup.status != TopupStatus.INITIATED:
        return _view(topup, replay=not created)
    topup_id = topup.id
    release_read_transaction(session)

    try:
        accepted = provider.stk_push(
            StkPushRequest(
                amount_cents=amount,
                phone_e164=phone_e164,
                account_reference=_ACCOUNT_REFERENCE,
                description=_DESCRIPTION,
                callback_url=callback_url(provider.name),
                idempotency_key=f"topup:{topup_id}",
            )
        )
    except ProviderError as exc:
        if 400 <= exc.http_status < 500:
            return _view(_record_refusal(session, topup_id, str(exc), now), replay=not created)
        raise
    except httpx.HTTPError as exc:
        raise ProviderError("M-PESA did not answer; retry with the same Idempotency-Key") from exc
    return _view(_record_accepted(session, topup_id, accepted, now), replay=not created)


def handle_stk_callback(
    session: Session,
    provider: PaymentsProvider,
    payload: Mapping[str, Any],
    now: datetime | None = None,
) -> CallbackDisposition:
    """Record a callback and apply it if it is the first final answer for its top-up."""
    callback = provider.parse_stk_callback(payload)
    now = now or datetime.now(UTC)
    release_read_transaction(session)
    with session.begin():
        topup = session.scalar(
            select(Topup)
            .where(Topup.checkout_request_id == callback.checkout_request_id)
            .with_for_update()
        )
        result = RailResult(
            result_code=callback.result_code,
            result_desc=callback.result_desc,
            amount_cents=callback.amount_cents,
            receipt=callback.mpesa_receipt_number,
        )
        disposition = (
            _apply(session, topup, result, now)
            if topup is not None
            else CallbackDisposition.UNMATCHED
        )
        session.add(
            StkCallbackLog(
                id=uuid4(),
                checkout_request_id=callback.checkout_request_id,
                topup_id=topup.id if topup is not None else None,
                result_code=callback.result_code,
                disposition=disposition.value,
                payload=dict(payload),
            )
        )
    if disposition is CallbackDisposition.UNMATCHED:
        logger.warning(
            "STK callback for unknown CheckoutRequestID %s", callback.checkout_request_id
        )
    return disposition


def get_topup(
    session: Session,
    rails: Rails,
    *,
    topup_id: UUID,
    user_id: UUID,
    now: datetime | None = None,
) -> TopupView:
    """Read a top-up. A stale one is first resolved with STK Query."""
    topup = session.get(Topup, topup_id)
    if topup is None or topup.user_id != user_id:
        raise TopupNotFound("no such top-up")
    provider = rails.for_topup(topup.provider)
    return _view(resolve_topup(session, provider, topup_id, now=now))


def resolve_stale_topups(session: Session, rails: Rails, now: datetime | None = None) -> int:
    """Run STK Query for every top-up that is waiting too long. Returns how many changed."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=get_settings().stk_query_after_seconds)
    ids = session.scalars(
        select(Topup.id).where(
            Topup.status.in_([TopupStatus.INITIATED.value, TopupStatus.PENDING.value]),
            Topup.created_at <= cutoff,
        )
    ).all()
    changed = 0
    for topup_id in ids:
        before = session.get(Topup, topup_id)
        if before is None:
            continue
        status_before = before.status
        after = resolve_topup(session, rails.for_topup(before.provider), topup_id, now=now)
        changed += int(after.status != status_before)
    return changed


def resolve_topup(
    session: Session,
    provider: PaymentsProvider | None,
    topup_id: UUID,
    now: datetime | None = None,
) -> Topup:
    """Ask the rail about a top-up waiting too long, and expire it once it is too old.

    With no provider (its rail is no longer offered), the top-up can only expire.
    """
    settings = get_settings()
    now = now or datetime.now(UTC)
    topup = session.get(Topup, topup_id, populate_existing=True)
    if topup is None:
        raise TopupNotFound("no such top-up")
    age = now - topup.created_at
    status = TopupStatus(topup.status)
    checkout_request_id = topup.checkout_request_id
    if status not in (TopupStatus.INITIATED, TopupStatus.PENDING):
        return topup
    if age < timedelta(seconds=settings.stk_query_after_seconds):
        return topup
    give_up = age >= timedelta(seconds=settings.stk_expire_after_seconds)
    recently_queried = topup.queried_at is not None and now - topup.queried_at < timedelta(
        seconds=settings.stk_query_interval_seconds
    )
    if recently_queried and not give_up:
        return topup
    release_read_transaction(session)

    queried = False
    answer: RailResult | None = None
    if status is TopupStatus.PENDING and checkout_request_id is not None and provider is not None:
        queried = True
        try:
            query = provider.stk_query(checkout_request_id)
        except (ProviderError, httpx.HTTPError):
            logger.warning("STK Query failed for top-up %s", topup.id, exc_info=True)
            query = None
        if query is not None and not query.processing and query.result_code is not None:
            answer = RailResult(result_code=query.result_code, result_desc=query.result_desc)
    if not queried and not give_up:
        return topup

    with session.begin():
        locked = session.scalar(select(Topup).where(Topup.id == topup_id).with_for_update())
        assert locked is not None
        if TopupStatus(locked.status) in (TopupStatus.INITIATED, TopupStatus.PENDING):
            if queried:
                locked.queried_at = now
            if answer is not None:
                _apply(session, locked, answer, now)
            elif give_up:
                transition(locked, TopupStatus.EXPIRED, now)
                locked.result_desc = "No answer from M-PESA before the top-up expired"
    session.refresh(locked)
    return locked


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
) -> tuple[Topup, bool]:
    release_read_transaction(session)
    for _ in range(3):
        try:
            with session.begin():
                existing = session.scalar(
                    select(Topup).where(Topup.user_id == user_id, Topup.idempotency_key == key)
                )
                if existing is not None:
                    if existing.request_hash != digest:
                        raise IdempotencyConflict(
                            "Idempotency-Key was already used for a different top-up"
                        )
                    return existing, False
                topup = Topup(
                    id=uuid4(),
                    user_id=user_id,
                    wallet_account_id=wallet_account_id,
                    idempotency_key=key,
                    request_hash=digest,
                    amount_cents=amount,
                    phone_e164=phone,
                    status=TopupStatus.INITIATED.value,
                    provider=provider_name,
                    updated_at=now,
                )
                session.add(topup)
            return topup, True
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) != _UNIQUE_VIOLATION:
                raise
    raise LedgerError("could not create the top-up after concurrent retries")


def _record_accepted(
    session: Session, topup_id: UUID, accepted: StkPushAccepted, now: datetime
) -> Topup:
    release_read_transaction(session)
    with session.begin():
        topup = session.scalar(select(Topup).where(Topup.id == topup_id).with_for_update())
        assert topup is not None
        if topup.status == TopupStatus.INITIATED:
            topup.merchant_request_id = accepted.merchant_request_id
            topup.checkout_request_id = accepted.checkout_request_id
            transition(topup, TopupStatus.PENDING, now)
            session.flush()
            _apply_early_callback(session, topup, now)
    session.refresh(topup)
    return topup


def _apply_early_callback(session: Session, topup: Topup, now: datetime) -> None:
    """A callback can beat the push response here. Apply it now that the id is known."""
    early = session.scalars(
        select(StkCallbackLog)
        .where(
            StkCallbackLog.checkout_request_id == topup.checkout_request_id,
            StkCallbackLog.disposition == CallbackDisposition.UNMATCHED.value,
        )
        .order_by(StkCallbackLog.received_at, StkCallbackLog.id)
        .with_for_update()
    ).all()
    for log in early:
        callback = _parse_logged(log)
        log.topup_id = topup.id
        log.disposition = _apply(session, topup, callback, now).value


def _record_refusal(session: Session, topup_id: UUID, reason: str, now: datetime) -> Topup:
    release_read_transaction(session)
    with session.begin():
        topup = session.scalar(select(Topup).where(Topup.id == topup_id).with_for_update())
        assert topup is not None
        if topup.status == TopupStatus.INITIATED:
            transition(topup, TopupStatus.FAILED, now)
            topup.result_desc = reason[:300]
    session.refresh(topup)
    return topup


def _apply(
    session: Session, topup: Topup, result: RailResult, now: datetime
) -> CallbackDisposition:
    status = TopupStatus(topup.status)
    if status in FINAL:
        if result.succeeded != (status is TopupStatus.SUCCEEDED):
            return CallbackDisposition.CONFLICT
        if result.receipt and topup.mpesa_receipt_number is None:
            topup.mpesa_receipt_number = result.receipt
        return CallbackDisposition.DUPLICATE
    if result.succeeded and result.amount_cents not in (None, topup.amount_cents):
        return CallbackDisposition.AMOUNT_MISMATCH

    topup.result_code = result.result_code
    topup.result_desc = result.result_desc[:300]
    if not result.succeeded:
        transition(topup, TopupStatus.FAILED, now)
        return CallbackDisposition.APPLIED

    posted = post_entry_in_transaction(
        session,
        PostCommand(
            idempotency_key=f"topup:{topup.id}",
            description=f"M-PESA STK top-up {topup.checkout_request_id}",
            external_ref=topup.checkout_request_id,
            postings=(
                PostingLine(MPESA_FLOAT.id, Direction.DEBIT, topup.amount_cents),
                PostingLine(topup.wallet_account_id, Direction.CREDIT, topup.amount_cents),
            ),
        ),
    )
    topup.journal_entry_id = posted.entry_id
    topup.mpesa_receipt_number = result.receipt
    transition(topup, TopupStatus.SUCCEEDED, now)
    return CallbackDisposition.APPLIED


def _parse_logged(log: StkCallbackLog) -> RailResult:
    callback = parse_stk_callback(log.payload)
    return RailResult(
        result_code=callback.result_code,
        result_desc=callback.result_desc,
        amount_cents=callback.amount_cents,
        receipt=callback.mpesa_receipt_number,
    )


def _require_topup_amount(value: object) -> int:
    amount = require_cents(value)
    if amount % 100 != 0:
        raise InvalidAmount("M-PESA top-ups must be a whole number of shillings")
    cap = min(MAX_TOPUP_CENTS, get_settings().topup_max_cents)
    if amount > cap:
        raise InvalidAmount(f"a top-up cannot exceed KES {cap // 100:,}")
    return amount


def _request_hash(amount: int, phone: str) -> str:
    encoded = json.dumps({"amount_cents": amount, "phone": phone}, sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _view(topup: Topup, *, replay: bool = False) -> TopupView:
    return TopupView(
        id=topup.id,
        status=TopupStatus(topup.status),
        rail=topup.provider,
        amount_cents=topup.amount_cents,
        phone_e164=topup.phone_e164,
        checkout_request_id=topup.checkout_request_id,
        mpesa_receipt_number=topup.mpesa_receipt_number,
        result_code=topup.result_code,
        result_desc=topup.result_desc,
        created_at=topup.created_at,
        resolved_at=topup.resolved_at,
        idempotent_replay=replay,
    )
