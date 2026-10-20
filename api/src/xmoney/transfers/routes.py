"""Send to an @handle."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.orm import Session

from xmoney.auth.deps import current_user
from xmoney.auth.service import SessionUser
from xmoney.db import get_db
from xmoney.ratelimit.deps import limit_by_user
from xmoney.ratelimit.service import SEND
from xmoney.transfers.fees import quote_p2p
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
    fee_cents: int
    fee_schedule_version: int
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
            fee_cents=view.fee_cents,
            fee_schedule_version=view.fee_schedule_version,
            note=view.note,
            created_at=view.created_at,
            idempotent_replay=view.idempotent_replay,
        )


class TransferQuoteOut(BaseModel):
    amount_cents: int
    fee_cents: int
    total_cents: int
    fee_schedule_version: int
    waived: bool


@router.get("/transfers/quote", response_model=TransferQuoteOut)
def quote_transfer(
    amount_cents: StrictInt = Query(..., examples=[12_000]),
    user: SessionUser = Depends(current_user),
    session: Session = Depends(get_db),
) -> TransferQuoteOut:
    """Price a send under the schedule in force, including any remaining free allowance."""
    quote = quote_p2p(session, sender_user_id=user.user_id, amount_cents=amount_cents)
    return TransferQuoteOut(
        amount_cents=quote.amount_cents,
        fee_cents=quote.fee_cents,
        total_cents=quote.total_cents,
        fee_schedule_version=quote.schedule_version,
        waived=quote.waived,
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
