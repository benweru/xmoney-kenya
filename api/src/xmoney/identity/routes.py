"""Registration and public @handle lookup."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from xmoney.db import get_db
from xmoney.identity.schemas import HandleOut, RegisterIn, UserOut
from xmoney.identity.service import lookup_handle, register_user

router = APIRouter(tags=["identity"])


@router.post("/users", response_model=UserOut, status_code=201)
def register(body: RegisterIn, session: Session = Depends(get_db)) -> UserOut:
    user = register_user(session, handle=body.handle, phone=body.phone, pin=body.pin)
    return UserOut(
        id=user.id,
        handle=user.handle,
        phone=user.phone_e164,
        wallet_account_id=user.wallet_account_id,
        created_at=user.created_at,
    )


@router.get("/handles/{handle}", response_model=HandleOut)
def get_handle(handle: str, session: Session = Depends(get_db)) -> HandleOut:
    record = lookup_handle(session, handle)
    return HandleOut(
        handle=record.handle,
        user_id=record.user_id,
        wallet_account_id=record.wallet_account_id,
    )
