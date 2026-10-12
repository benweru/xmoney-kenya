"""Balance reads and a sandbox-only journal endpoint.

The journal route exists so the ledger can be demonstrated. Customer top-ups
will not post through it; week 2 posts from an STK callback, idempotently.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from xmoney.config import get_settings
from xmoney.db import get_db
from xmoney.errors import LedgerError, SandboxViolation
from xmoney.ledger.models import JournalEntry, Posting
from xmoney.ledger.schemas import BalanceOut, JournalEntryOut, PostEntryIn, PostingOut
from xmoney.ledger.service import get_balance, post_entry

router = APIRouter(tags=["ledger"])


@router.get("/accounts/{account_id}/balance", response_model=BalanceOut)
def read_balance(account_id: UUID, session: Session = Depends(get_db)) -> BalanceOut:
    balance = get_balance(session, account_id)
    return BalanceOut(
        account_id=balance.account_id,
        code=balance.code,
        currency=balance.currency,
        normal_side=balance.normal_side.value,
        debit_cents=balance.debit_cents,
        credit_cents=balance.credit_cents,
        balance_cents=balance.balance_cents,
    )


@router.post(
    "/sandbox/journal-entries",
    response_model=JournalEntryOut,
    responses={200: {"model": JournalEntryOut}, 201: {"model": JournalEntryOut}},
)
def create_sandbox_entry(body: PostEntryIn, session: Session = Depends(get_db)) -> JSONResponse:
    """Post a balanced entry. Replaying the same key and body returns the original."""
    if get_settings().sandbox_mode is not True:
        raise SandboxViolation("journal posting is disabled outside sandbox mode")
    result = post_entry(session, body.to_command())
    entry = session.get(JournalEntry, result.entry_id)
    if entry is None:
        raise LedgerError("journal entry disappeared after posting")
    lines = session.scalars(
        select(Posting).where(Posting.journal_entry_id == entry.id).order_by(Posting.line_no)
    ).all()
    payload = JournalEntryOut(
        id=entry.id,
        idempotency_key=entry.idempotency_key,
        description=entry.description,
        external_ref=entry.external_ref,
        idempotent_replay=not result.created,
        postings=[
            PostingOut(
                line_no=line.line_no,
                account_id=line.account_id,
                direction=line.direction,
                amount_cents=line.amount_cents,
            )
            for line in lines
        ],
    )
    return JSONResponse(
        status_code=201 if result.created else 200,
        content=payload.model_dump(mode="json"),
    )
