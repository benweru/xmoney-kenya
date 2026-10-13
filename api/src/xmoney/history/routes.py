"""The signed-in user's transaction history."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from xmoney.auth.deps import current_user
from xmoney.auth.service import SessionUser
from xmoney.db import get_db
from xmoney.history.service import DEFAULT_LIMIT, MAX_LIMIT, HistoryItem, wallet_history

router = APIRouter(tags=["history"])


class HistoryItemOut(BaseModel):
    id: UUID
    kind: str
    amount_cents: int
    counterparty: str | None
    note: str | None
    mpesa_receipt: str | None
    created_at: datetime

    @classmethod
    def of(cls, item: HistoryItem) -> HistoryItemOut:
        return cls(
            id=item.entry_id,
            kind=item.kind.value,
            amount_cents=item.amount_cents,
            counterparty=item.counterparty,
            note=item.note,
            mpesa_receipt=item.mpesa_receipt,
            created_at=item.created_at,
        )


class HistoryPageOut(BaseModel):
    items: list[HistoryItemOut]
    next_cursor: str | None


@router.get("/me/transactions", response_model=HistoryPageOut)
def list_my_transactions(
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(default=None, max_length=200),
    user: SessionUser = Depends(current_user),
    session: Session = Depends(get_db),
) -> HistoryPageOut:
    """Newest first. Pass `next_cursor` back as `cursor` for the next page; null means done.

    `amount_cents` is signed: positive into the wallet, negative out of it.
    """
    page = wallet_history(
        session,
        user_id=user.user_id,
        wallet_account_id=user.wallet_account_id,
        limit=limit,
        cursor=cursor,
    )
    return HistoryPageOut(
        items=[HistoryItemOut.of(item) for item in page.items], next_cursor=page.next_cursor
    )
