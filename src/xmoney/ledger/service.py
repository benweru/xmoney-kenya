"""Post balanced journal entries and read balances from postings.

`post_entry` commits. It locks every account it touches, in id order, so
concurrent posts cannot deadlock. Spend limits are not applied here: a wallet
may go negative until week 3 adds transfer rules. The database still rejects
an entry whose debits do not equal its credits, and it rejects updates.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xmoney.errors import AccountNotFound, IdempotencyConflict, LedgerError, UnbalancedEntry
from xmoney.ledger.models import JournalEntry, LedgerAccount, NormalSide, Posting
from xmoney.ledger.money import PostCommand, PostResult, request_hash, validate_command
from xmoney.ledger.system import SYSTEM_ACCOUNTS

_UNIQUE_VIOLATION = "23505"
_CHECK_VIOLATION = "23514"


@dataclass(frozen=True)
class AccountBalance:
    account_id: UUID
    code: str
    currency: str
    normal_side: NormalSide
    debit_cents: int
    credit_cents: int
    balance_cents: int


def seed_system_accounts(session: Session) -> None:
    """Insert the chart of accounts. Existing rows are left untouched."""
    for spec in SYSTEM_ACCOUNTS:
        if session.get(LedgerAccount, spec.id) is None:
            session.add(
                LedgerAccount(
                    id=spec.id,
                    code=spec.code,
                    name=spec.name,
                    account_type=spec.account_type.value,
                    normal_side=spec.normal_side.value,
                    currency="KES",
                    owner_user_id=None,
                )
            )


def post_entry(session: Session, command: PostCommand) -> PostResult:
    """Insert a balanced entry, or return the original when the key is reused."""
    command = validate_command(command)
    digest = request_hash(command)
    if session.in_transaction():
        session.rollback()

    for _ in range(5):
        try:
            with session.begin():
                existing = session.scalar(
                    select(JournalEntry).where(
                        JournalEntry.idempotency_key == command.idempotency_key
                    )
                )
                if existing is not None:
                    _assert_same_request(existing, digest)
                    result = PostResult(
                        entry_id=existing.id,
                        idempotency_key=existing.idempotency_key,
                        request_hash=existing.request_hash,
                        created=False,
                    )
                else:
                    entry_id = uuid4()
                    session.add(
                        JournalEntry(
                            id=entry_id,
                            idempotency_key=command.idempotency_key,
                            request_hash=digest,
                            description=command.description,
                            external_ref=command.external_ref,
                        )
                    )
                    session.flush()
                    _lock_accounts_and_post(session, entry_id, command)
                    result = PostResult(
                        entry_id=entry_id,
                        idempotency_key=command.idempotency_key,
                        request_hash=digest,
                        created=True,
                    )
            return result
        except IntegrityError as exc:
            state = _sqlstate(exc)
            if state == _UNIQUE_VIOLATION:
                continue
            if state == _CHECK_VIOLATION and "unbalanced" in str(exc):
                raise UnbalancedEntry("journal entry is unbalanced") from exc
            raise
    raise LedgerError("could not post the journal entry after concurrent retries")


def get_balance(session: Session, account_id: UUID) -> AccountBalance:
    account = session.get(LedgerAccount, account_id)
    if account is None:
        raise AccountNotFound(f"unknown account {account_id}")
    debits, credits = _account_sums(session, account_id)
    normal = NormalSide(account.normal_side)
    balance = debits - credits if normal is NormalSide.DEBIT else credits - debits
    return AccountBalance(
        account_id=account.id,
        code=account.code,
        currency=account.currency,
        normal_side=normal,
        debit_cents=debits,
        credit_cents=credits,
        balance_cents=balance,
    )


def trial_totals(session: Session) -> tuple[int, int]:
    """Return (sum of debits, sum of credits) across every posting."""
    row = session.execute(
        select(
            func.coalesce(
                func.sum(Posting.amount_cents).filter(Posting.direction == "debit"),
                0,
            ),
            func.coalesce(
                func.sum(Posting.amount_cents).filter(Posting.direction == "credit"),
                0,
            ),
        )
    ).one()
    return int(row[0]), int(row[1])


def _assert_same_request(existing: JournalEntry, digest: str) -> None:
    if existing.request_hash != digest:
        raise IdempotencyConflict("idempotency key was already used with a different journal entry")


def _lock_accounts_and_post(session: Session, entry_id: UUID, command: PostCommand) -> None:
    account_ids = sorted({line.account_id for line in command.postings})
    rows = session.scalars(
        select(LedgerAccount)
        .where(LedgerAccount.id.in_(account_ids))
        .order_by(LedgerAccount.id)
        .with_for_update()
    ).all()
    found = {row.id for row in rows}
    missing = [str(account_id) for account_id in account_ids if account_id not in found]
    if missing:
        raise AccountNotFound("unknown account(s): " + ", ".join(missing))
    for row in rows:
        if row.currency != "KES":
            raise LedgerError(f"account {row.code} is not a KES account")
    for index, line in enumerate(command.postings, start=1):
        session.add(
            Posting(
                id=uuid4(),
                journal_entry_id=entry_id,
                account_id=line.account_id,
                line_no=index,
                direction=line.direction.value,
                amount_cents=line.amount_cents,
            )
        )


def _account_sums(session: Session, account_id: UUID) -> tuple[int, int]:
    row = session.execute(
        select(
            func.coalesce(
                func.sum(Posting.amount_cents).filter(Posting.direction == "debit"),
                0,
            ),
            func.coalesce(
                func.sum(Posting.amount_cents).filter(Posting.direction == "credit"),
                0,
            ),
        ).where(Posting.account_id == account_id)
    ).one()
    return int(row[0]), int(row[1])


def _sqlstate(exc: IntegrityError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)
