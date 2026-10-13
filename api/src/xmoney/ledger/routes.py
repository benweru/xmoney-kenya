"""Balance reads for the signed-in owner, and a local-development journal endpoint.

The journal route exists so the ledger can be demonstrated on a laptop. It is
off by default. Customer top-ups do not post through it; they post from the
STK callback, idempotently.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from xmoney.auth.deps import current_user
from xmoney.auth.service import SessionUser
from xmoney.config import get_settings
from xmoney.db import get_db
from xmoney.errors import AccountNotFound, LedgerError, NotFound, SandboxViolation
from xmoney.ledger.models import JournalEntry, LedgerAccount, Posting
from xmoney.ledger.schemas import BalanceOut, JournalEntryOut, PostEntryIn, PostingOut
from xmoney.ledger.service import AccountBalance, get_balance, post_entry

router = APIRouter(tags=["ledger"])


@router.get("/me/balance", response_model=BalanceOut)
def read_my_balance(
    user: SessionUser = Depends(current_user), session: Session = Depends(get_db)
) -> BalanceOut:
    return _balance_out(get_balance(session, user.wallet_account_id))


@router.get("/accounts/{account_id}/balance", response_model=BalanceOut)
def read_balance(
    account_id: UUID,
    user: SessionUser = Depends(current_user),
    session: Session = Depends(get_db),
) -> BalanceOut:
    """Only the account's owner may read it. Anything else is a 404, so ids reveal nothing."""
    account = session.get(LedgerAccount, account_id)
    if account is None or account.owner_user_id != user.user_id:
        raise AccountNotFound(f"unknown account {account_id}")
    return _balance_out(get_balance(session, account_id))


def _balance_out(balance: AccountBalance) -> BalanceOut:
    return BalanceOut(
        account_id=balance.account_id,
        code=balance.code,
        currency=balance.currency,
        normal_side=balance.normal_side.value,
        debit_cents=balance.debit_cents,
        credit_cents=balance.credit_cents,
        balance_cents=balance.balance_cents,
    )


def require_sandbox_journal() -> None:
    settings = get_settings()
    if settings.sandbox_mode is not True:
        raise SandboxViolation("journal posting is disabled outside sandbox mode")
    if not settings.sandbox_journal_enabled:
        raise NotFound("not found")


@router.post(
    "/sandbox/journal-entries",
    response_model=JournalEntryOut,
    responses={200: {"model": JournalEntryOut}, 201: {"model": JournalEntryOut}},
    dependencies=[Depends(require_sandbox_journal)],
)
def create_sandbox_entry(body: PostEntryIn, session: Session = Depends(get_db)) -> JSONResponse:
    """Local development only: 404 unless `SANDBOX_JOURNAL_ENABLED=true`.

    Posts any balanced entry, including a credit to any wallet, so it never runs
    on the public demo. Replaying the same key and body returns the original.
    """
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
