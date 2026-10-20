"""Top-up and cash-out endpoints, plus Daraja STK and B2C callbacks."""

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
from xmoney.identity.validators import normalize_phone
from xmoney.payments.cashouts import get_cashout, handle_b2c_callback, start_cashout
from xmoney.payments.deps import RAIL_LABELS, Rails, get_rails
from xmoney.payments.schemas import CashoutIn, CashoutOut, RailOut, RailsOut, TopupIn, TopupOut
from xmoney.payments.topups import get_topup, handle_stk_callback, start_topup
from xmoney.ratelimit.deps import limit_by_user
from xmoney.ratelimit.service import START_CASHOUT, START_TOPUP

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
    rails: Rails = Depends(get_rails),
) -> JSONResponse:
    """Queue an STK Push. Poll GET /v1/topups/{id} until the worker has sent it."""
    phone = normalize_phone(body.phone or user.phone_e164)
    view = start_topup(
        session,
        rails.for_new_topup(body.rail, phone),
        user_id=user.user_id,
        wallet_account_id=user.wallet_account_id,
        phone=phone,
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
    rails: Rails = Depends(get_rails),
) -> TopupOut:
    """Current state. A top-up with no callback yet is checked with STK Query first."""
    return TopupOut.of(get_topup(session, rails, topup_id=topup_id, user_id=user.user_id))


@router.get("/payment-rails", response_model=RailsOut)
def list_rails(rails: Rails = Depends(get_rails)) -> RailsOut:
    """The rails a top-up can use here, default first."""
    return RailsOut(
        default=rails.default,
        rails=[
            RailOut(
                name=name,
                label=RAIL_LABELS.get(name, name),
                restricted=name == "sandbox" and bool(rails.sandbox_phones),
            )
            for name in rails.names
        ],
    )


@router.post(
    "/cashouts",
    response_model=CashoutOut,
    status_code=201,
    responses={200: {"model": CashoutOut, "description": "Idempotent replay"}},
    dependencies=[Depends(limit_by_user(START_CASHOUT))],
)
def create_cashout(
    body: CashoutIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: SessionUser = Depends(current_user),
    session: Session = Depends(get_db),
    rails: Rails = Depends(get_rails),
) -> JSONResponse:
    """Hold wallet funds and queue a B2C payment. Poll GET /v1/cashouts/{id}."""
    phone = normalize_phone(body.phone or user.phone_e164)
    view = start_cashout(
        session,
        rails.for_new_topup(body.rail, phone),
        user_id=user.user_id,
        wallet_account_id=user.wallet_account_id,
        phone=phone,
        amount_cents=body.amount_cents,
        idempotency_key=idempotency_key,
    )
    return JSONResponse(
        status_code=200 if view.idempotent_replay else 201,
        content=CashoutOut.of(view).model_dump(mode="json"),
    )


@router.get("/cashouts/{cashout_id}", response_model=CashoutOut)
def read_cashout(
    cashout_id: UUID,
    user: SessionUser = Depends(current_user),
    session: Session = Depends(get_db),
) -> CashoutOut:
    """Current state. A cash-out waiting too long is expired or released here."""
    return CashoutOut.of(get_cashout(session, cashout_id=cashout_id, user_id=user.user_id))


@router.post("/payments/stk/callback/{token}")
def stk_callback(
    token: str,
    payload: dict[str, Any] = Body(...),
    session: Session = Depends(get_db),
    rails: Rails = Depends(get_rails),
) -> dict[str, object]:
    """Daraja's result callback. A success is logged; STK Query must confirm before credit."""
    if not hmac.compare_digest(token, get_settings().stk_callback_token):
        raise HTTPException(status_code=404)
    handle_stk_callback(session, rails.any(), payload)
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/payments/b2c/result/{token}")
def b2c_result(
    token: str,
    payload: dict[str, Any] = Body(...),
    session: Session = Depends(get_db),
    rails: Rails = Depends(get_rails),
) -> dict[str, object]:
    """Daraja's B2C result. Success settles the hold; failure releases it."""
    if not hmac.compare_digest(token, get_settings().stk_callback_token):
        raise HTTPException(status_code=404)
    handle_b2c_callback(session, rails.any(), payload, timed_out=False)
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/payments/b2c/timeout/{token}")
def b2c_timeout(
    token: str,
    payload: dict[str, Any] = Body(...),
    session: Session = Depends(get_db),
    rails: Rails = Depends(get_rails),
) -> dict[str, object]:
    """Daraja's B2C timeout. The hold stays in clearing until a late result or staff."""
    if not hmac.compare_digest(token, get_settings().stk_callback_token):
        raise HTTPException(status_code=404)
    handle_b2c_callback(session, rails.any(), payload, timed_out=True)
    return {"ResultCode": 0, "ResultDesc": "Accepted"}
