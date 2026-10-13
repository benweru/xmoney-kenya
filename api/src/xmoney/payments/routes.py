"""Top-up endpoints and the STK callback Daraja posts to."""

from __future__ import annotations

import hmac
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from xmoney.auth.deps import current_user
from xmoney.auth.service import SessionUser
from xmoney.config import get_settings
from xmoney.db import get_db
from xmoney.payments.deps import get_payments_provider
from xmoney.payments.provider import PaymentsProvider
from xmoney.payments.schemas import TopupIn, TopupOut
from xmoney.payments.topups import get_topup, handle_stk_callback, start_topup
from xmoney.ratelimit.deps import limit_by_user
from xmoney.ratelimit.service import START_TOPUP

router = APIRouter(tags=["top-ups"])


@router.post(
    "/topups",
    response_model=TopupOut,
    status_code=201,
    responses={200: {"model": TopupOut, "description": "Idempotent replay"}},
    dependencies=[Depends(limit_by_user(START_TOPUP))],
)
def create_topup(
    body: TopupIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: SessionUser = Depends(current_user),
    session: Session = Depends(get_db),
    provider: PaymentsProvider = Depends(get_payments_provider),
) -> JSONResponse:
    """Send an STK Push to the phone. Poll GET /v1/topups/{id} for the result."""
    view = start_topup(
        session,
        provider,
        user_id=user.user_id,
        wallet_account_id=user.wallet_account_id,
        phone=body.phone or user.phone_e164,
        amount_cents=body.amount_cents,
        idempotency_key=idempotency_key,
    )
    return JSONResponse(
        status_code=200 if view.idempotent_replay else 201,
        content=TopupOut.of(view).model_dump(mode="json"),
    )


@router.get("/topups/{topup_id}", response_model=TopupOut)
def read_topup(
    topup_id: UUID,
    user: SessionUser = Depends(current_user),
    session: Session = Depends(get_db),
    provider: PaymentsProvider = Depends(get_payments_provider),
) -> TopupOut:
    """Current state. A top-up with no callback yet is checked with STK Query first."""
    return TopupOut.of(get_topup(session, provider, topup_id=topup_id, user_id=user.user_id))


@router.post("/payments/stk/callback/{token}")
def stk_callback(
    token: str,
    payload: dict[str, Any] = Body(...),
    session: Session = Depends(get_db),
    provider: PaymentsProvider = Depends(get_payments_provider),
) -> dict[str, object]:
    """Daraja's result callback. Duplicates and unknown ids are acknowledged and logged."""
    if not hmac.compare_digest(token, get_settings().stk_callback_token):
        raise HTTPException(status_code=404)
    handle_stk_callback(session, provider, payload)
    return {"ResultCode": 0, "ResultDesc": "Accepted"}
