"""Post balanced journal entries and read balances from postings.

`post_entry` commits. `post_entry_in_transaction` posts inside the caller's
transaction, for flows such as an STK callback where a payment row and its
entry must commit together. Both lock accounts that may not go negative, in
id order, so concurrent wallet posts cannot deadlock. System accounts such
as the M-PESA float are not locked (see ADR 010). Spend limits are not
applied here. The database still rejects an entry whose debits do not equal
its credits, and it rejects updates.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xmoney.db import release_read_transaction
from xmoney.errors import AccountNotFound, IdempotencyConflict, LedgerError, UnbalancedEntry
from xmoney.ledger.models import JournalEntry, LedgerAccount, NormalSide, Posting
from xmoney.ledger.money import PostCommand, PostResult, request_hash, validate_command
from xmoney.ledger.system import SYSTEM_ACCOUNTS

_UNIQUE_VIOLATION = "23505"
_CHECK_VIOLATION = "23514"
_RETRIES = 5


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
                    allow_negative=True,
                )
            )


def post_entry(session: Session, command: PostCommand) -> PostResult:
    """Insert a balanced entry in its own transaction, or return the original on replay."""
    command = validate_command(command)
    digest = request_hash(command)
    release_read_transaction(session)

    for _ in range(_RETRIES):
        try:
            with session.begin():
                result = _post_once(session, command, digest)
            return result
        except IntegrityError as exc:
            _reraise_unless_key_race(exc)
    raise LedgerError("could not post the journal entry after concurrent retries")


def post_entry_in_transaction(session: Session, command: PostCommand) -> PostResult:
    """Post inside the caller's transaction, so the entry commits with the caller's rows.

    The insert runs under a savepoint. Losing an idempotency-key race rolls back
    only the savepoint, and the retry returns the winner's entry. Nothing is
    visible to other sessions until the caller commits.
    """
    command = validate_command(command)
    digest = request_hash(command)
    for _ in range(_RETRIES):
        try:
            with session.begin_nested():
                return _post_once(session, command, digest)
        except IntegrityError as exc:
            _reraise_unless_key_race(exc)
    raise LedgerError("could not post the journal entry after concurrent retries")


def _post_once(session: Session, command: PostCommand, digest: str) -> PostResult:
    existing = session.scalar(
        select(JournalEntry).where(JournalEntry.idempotency_key == command.idempotency_key)
    )
    if existing is not None:
        _assert_same_request(existing, digest)
        return PostResult(
            entry_id=existing.id,
            idempotency_key=existing.idempotency_key,
            request_hash=existing.request_hash,
            created=False,
        )
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
    session.flush()
    return PostResult(
        entry_id=entry_id,
        idempotency_key=command.idempotency_key,
        request_hash=digest,
        created=True,
    )


def _reraise_unless_key_race(exc: IntegrityError) -> None:
    state = _sqlstate(exc)
    if state == _UNIQUE_VIOLATION:
        return
    if state == _CHECK_VIOLATION and "unbalanced" in str(exc):
        raise UnbalancedEntry("journal entry is unbalanced") from exc
    raise exc


def get_balance(session: Session, account_id: UUID) -> AccountBalance:
    account = session.get(LedgerAccount, account_id)
    if account is None:
        raise AccountNotFound(f"unknown account {account_id}")
    if account.allow_negative:
        debits, credits = _account_sums(session, account_id)
    else:
        debits, credits = _wallet_running_sums(session, account_id)
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


def lock_accounts(session: Session, account_ids: Iterable[UUID]) -> Sequence[LedgerAccount]:
    """Lock accounts in id order, the order every poster uses, so lockers cannot deadlock.

    Pass wallet ids. System accounts that may go negative are not locked here
    either; `_lock_accounts_and_post` filters them out. Balances read after
    this, in the same transaction, include every committed posting and cannot
    change until the transaction ends.
    """
    return _load_accounts(session, account_ids, for_update=True)


def _load_accounts(
    session: Session, account_ids: Iterable[UUID], *, for_update: bool = False
) -> Sequence[LedgerAccount]:
    ordered = sorted(set(account_ids))
    if not ordered:
        return []
    stmt = select(LedgerAccount).where(LedgerAccount.id.in_(ordered)).order_by(LedgerAccount.id)
    if for_update:
        stmt = stmt.with_for_update()
    rows = session.scalars(stmt).all()
    found = {row.id for row in rows}
    missing = [str(account_id) for account_id in ordered if account_id not in found]
    if missing:
        raise AccountNotFound("unknown account(s): " + ", ".join(missing))
    return rows


def _lock_accounts_and_post(session: Session, entry_id: UUID, command: PostCommand) -> None:
    rows = _load_accounts(session, (line.account_id for line in command.postings))
    lock_accounts(session, (row.id for row in rows if not row.allow_negative))
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


def _wallet_running_sums(session: Session, account_id: UUID) -> tuple[int, int]:
    row = session.execute(
        select(LedgerAccount.running_debit_cents, LedgerAccount.running_credit_cents).where(
            LedgerAccount.id == account_id
        )
    ).one()
    return int(row[0]), int(row[1])


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
