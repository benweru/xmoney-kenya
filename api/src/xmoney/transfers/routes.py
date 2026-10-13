"""Send to an @handle."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.orm import Session

from xmoney.auth.deps import current_user
from xmoney.auth.service import SessionUser
from xmoney.db import get_db
from xmoney.ratelimit.deps import limit_by_user
from xmoney.ratelimit.service import SEND
from xmoney.transfers.service import TransferView, send

router = APIRouter(tags=["transfers"])


class TransferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str = Field(examples=["@baraka"])
    # Strict so JSON 100.0 and "100" are rejected instead of coerced to cents.
    amount_cents: StrictInt = Field(examples=[25_000])
    note: str | None = Field(default=None, examples=["Lunch"])


class TransferOut(BaseModel):
    id: UUID
    sender: str
    recipient: str
    amount_cents: int
    note: str | None
    created_at: datetime
    idempotent_replay: bool

    @classmethod
    def of(cls, view: TransferView) -> TransferOut:
        return cls(
            id=view.id,
            sender=view.sender_handle,
            recipient=view.recipient_handle,
            amount_cents=view.amount_cents,
            note=view.note,
            created_at=view.created_at,
            idempotent_replay=view.idempotent_replay,
        )


@router.post(
    "/transfers",
    response_model=TransferOut,
    status_code=201,
    responses={200: {"model": TransferOut, "description": "Idempotent replay"}},
    dependencies=[Depends(limit_by_user(SEND))],
)
def create_transfer(
    body: TransferIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: SessionUser = Depends(current_user),
    session: Session = Depends(get_db),
) -> JSONResponse:
    """Move money from the signed-in wallet to an @handle. Refused if it would overdraw."""
    view = send(
        session,
        sender_user_id=user.user_id,
        sender_handle=user.handle,
        sender_wallet_id=user.wallet_account_id,
        to_handle=body.to,
        amount_cents=body.amount_cents,
        idempotency_key=idempotency_key,
        note=body.note,
    )
    return JSONResponse(
        status_code=200 if view.idempotent_replay else 201,
        content=TransferOut.of(view).model_dump(mode="json"),
    )
