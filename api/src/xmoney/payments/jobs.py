"""Outbox jobs for payment rails: STK Push and B2C payment.

The API only writes the business row and this job, in one transaction. The
worker calls Daraja (or the mock). Delivery is at least once: the rail takes
`topup:{id}` / `cashout:{id}` as the idempotency key, and a second claim of a
finished row is a no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from xmoney.db import get_sessionmaker, import_mapped_tables
from xmoney.errors import ProviderError
from xmoney.outbox.service import Claim, PermanentFailure
from xmoney.outbox.worker import Handler
from xmoney.payments.cashouts import (
    record_accepted as record_b2c_accepted,
)
from xmoney.payments.cashouts import (
    record_refusal as record_b2c_refusal,
)
from xmoney.payments.cashouts import (
    result_url,
    timeout_url,
)
from xmoney.payments.deps import Rails, build_rails
from xmoney.payments.models import Cashout, CashoutStatus, Topup, TopupStatus
from xmoney.payments.provider import B2cPaymentRequest, PaymentsProvider, StkPushRequest
from xmoney.payments.topups import (
    _ACCOUNT_REFERENCE,
    _DESCRIPTION,
    _record_accepted,
    _record_refusal,
    callback_url,
)

STK_PUSH = "stk.push"
B2C_PAYMENT = "b2c.payment"
_B2C_REMARKS = "Wallet cashout"
_B2C_OCCASION = "Cashout"


def enqueue_stk_push(session: Session, topup_id: UUID, now: datetime | None = None) -> UUID:
    """Add the push job. Must be called in the same transaction that inserted the top-up."""
    from xmoney.outbox.service import enqueue

    return enqueue(
        session,
        STK_PUSH,
        {"topup_id": str(topup_id)},
        dedupe_key=f"{STK_PUSH}:{topup_id}",
        now=now,
    )


def enqueue_b2c_payment(session: Session, cashout_id: UUID, now: datetime | None = None) -> UUID:
    """Add the B2C job. Must be called in the same transaction that inserted the cash-out."""
    from xmoney.outbox.service import enqueue

    return enqueue(
        session,
        B2C_PAYMENT,
        {"cashout_id": str(cashout_id)},
        dedupe_key=f"{B2C_PAYMENT}:{cashout_id}",
        now=now,
    )


def production_handlers() -> dict[str, Handler]:
    """Handlers the long-running worker process registers."""
    return {STK_PUSH: handle_stk_push, B2C_PAYMENT: handle_b2c_payment}


def handle_stk_push(claim: Claim) -> None:
    import_mapped_tables()
    rails = build_rails()
    try:
        with get_sessionmaker()() as session:
            dispatch_stk_push(session, rails, claim)
    finally:
        rails.close()


def dispatch_stk_push(
    session: Session,
    rail: PaymentsProvider | Rails,
    claim: Claim,
    now: datetime | None = None,
) -> None:
    """Send one claimed STK Push. Tests pass a provider; the worker passes Rails."""
    now = now or datetime.now(UTC)
    try:
        topup_id = UUID(str(claim.payload["topup_id"]))
    except (KeyError, ValueError) as exc:
        raise PermanentFailure(f"stk.push payload is not a top-up id: {claim.payload}") from exc

    topup = session.get(Topup, topup_id)
    if topup is None:
        raise PermanentFailure(f"top-up {topup_id} is gone")
    if TopupStatus(topup.status) is not TopupStatus.INITIATED:
        return

    provider = _provider_for(rail, topup.provider)
    if provider is None:
        reason = "this process no longer offers that payment rail"
        _record_refusal(session, topup_id, reason, now)
        raise PermanentFailure(f"rail {topup.provider} is not offered")

    try:
        accepted = provider.stk_push(
            StkPushRequest(
                amount_cents=topup.amount_cents,
                phone_e164=topup.phone_e164,
                account_reference=_ACCOUNT_REFERENCE,
                description=_DESCRIPTION,
                callback_url=callback_url(provider.name),
                idempotency_key=f"topup:{topup.id}",
            )
        )
    except ProviderError as exc:
        _after_push_error(
            session, claim, topup_id, str(exc), now, permanent=400 <= exc.http_status < 500
        )
        raise
    except httpx.HTTPError as exc:
        message = "M-PESA did not answer; the worker will retry this push"
        _after_push_error(session, claim, topup_id, message, now, permanent=False)
        raise ProviderError(message) from exc

    _record_accepted(session, provider, topup_id, accepted, now)


def handle_b2c_payment(claim: Claim) -> None:
    import_mapped_tables()
    rails = build_rails()
    try:
        with get_sessionmaker()() as session:
            dispatch_b2c_payment(session, rails, claim)
    finally:
        rails.close()


def dispatch_b2c_payment(
    session: Session,
    rail: PaymentsProvider | Rails,
    claim: Claim,
    now: datetime | None = None,
) -> None:
    """Send one claimed B2C payment. Tests pass a provider; the worker passes Rails."""
    now = now or datetime.now(UTC)
    try:
        cashout_id = UUID(str(claim.payload["cashout_id"]))
    except (KeyError, ValueError) as exc:
        raise PermanentFailure(
            f"b2c.payment payload is not a cash-out id: {claim.payload}"
        ) from exc

    cashout = session.get(Cashout, cashout_id)
    if cashout is None:
        raise PermanentFailure(f"cash-out {cashout_id} is gone")
    if CashoutStatus(cashout.status) is not CashoutStatus.INITIATED:
        return

    provider = _provider_for(rail, cashout.provider)
    if provider is None:
        reason = "this process no longer offers that payment rail"
        record_b2c_refusal(session, cashout_id, reason, now)
        raise PermanentFailure(f"rail {cashout.provider} is not offered")

    try:
        accepted = provider.b2c_payment(
            B2cPaymentRequest(
                amount_cents=cashout.amount_cents,
                phone_e164=cashout.phone_e164,
                remarks=_B2C_REMARKS,
                occasion=_B2C_OCCASION,
                result_url=result_url(provider.name),
                timeout_url=timeout_url(provider.name),
                originator_conversation_id=cashout.originator_conversation_id,
                idempotency_key=f"cashout:{cashout.id}",
            )
        )
    except ProviderError as exc:
        _after_b2c_error(
            session, claim, cashout_id, str(exc), now, permanent=400 <= exc.http_status < 500
        )
        raise
    except httpx.HTTPError as exc:
        message = "M-PESA did not answer; the worker will retry this cash-out"
        _after_b2c_error(session, claim, cashout_id, message, now, permanent=False)
        raise ProviderError(message) from exc

    record_b2c_accepted(session, cashout_id, accepted, now)


def send_due(session: Session, rail: PaymentsProvider | Rails, now: datetime | None = None) -> None:
    """Run every due STK Push and B2C job against `rail`. For tests and the demo seeder."""
    from xmoney.outbox.worker import drain

    drain(
        session,
        {
            STK_PUSH: lambda claim: dispatch_stk_push(session, rail, claim, now),
            B2C_PAYMENT: lambda claim: dispatch_b2c_payment(session, rail, claim, now),
        },
        now=now,
    )


def _provider_for(rail: PaymentsProvider | Rails, name: str) -> PaymentsProvider | None:
    if isinstance(rail, Rails):
        return rail.for_topup(name)
    if rail.name == name:
        return rail
    return None


def _after_push_error(
    session: Session,
    claim: Claim,
    topup_id: UUID,
    message: str,
    now: datetime,
    *,
    permanent: bool,
) -> None:
    if permanent or claim.attempt >= claim.max_attempts:
        _record_refusal(session, topup_id, message, now)
    if permanent:
        raise PermanentFailure(message)


def _after_b2c_error(
    session: Session,
    claim: Claim,
    cashout_id: UUID,
    message: str,
    now: datetime,
    *,
    permanent: bool,
) -> None:
    if permanent or claim.attempt >= claim.max_attempts:
        record_b2c_refusal(session, cashout_id, message, now)
    if permanent:
        raise PermanentFailure(message)
