"""Ledger invariants: balance, idempotency, immutability, and the database checks."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from xmoney.errors import (
    AccountNotFound,
    IdempotencyConflict,
    InvalidAmount,
    InvalidJournal,
    UnbalancedEntry,
)
from xmoney.identity.service import register_user
from xmoney.ledger.models import JournalEntry, LedgerAccount, Posting
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import get_balance, post_entry
from xmoney.ledger.system import FEES, MPESA_FLOAT, SUSPENSE, SYSTEM_ACCOUNTS


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _command(
    wallet_id,
    *,
    key: str = "demo-entry-1",
    amount: int = 5_000,
    description: str = "Float to wallet",
    external_ref: str | None = None,
    reverse: bool = False,
) -> PostCommand:
    lines = (
        PostingLine(MPESA_FLOAT.id, Direction.DEBIT, amount),
        PostingLine(wallet_id, Direction.CREDIT, amount),
    )
    if reverse:
        lines = (lines[1], lines[0])
    return PostCommand(
        idempotency_key=key,
        description=description,
        external_ref=external_ref,
        postings=lines,
    )


def test_system_accounts_are_seeded_with_zero_balances(db: Session) -> None:
    rows = db.scalars(select(LedgerAccount).order_by(LedgerAccount.code)).all()
    assert [row.code for row in rows] == sorted(spec.code for spec in SYSTEM_ACCOUNTS)
    for spec in SYSTEM_ACCOUNTS:
        account = db.get(LedgerAccount, spec.id)
        assert account is not None
        assert account.account_type == spec.account_type.value
        assert account.normal_side == spec.normal_side.value
        assert account.currency == "KES"
        assert account.owner_user_id is None
        assert get_balance(db, spec.id).balance_cents == 0


def test_balanced_post_updates_derived_balances(db: Session) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    result = post_entry(db, _command(user.wallet_account_id))
    assert result.created is True
    assert get_balance(db, MPESA_FLOAT.id).balance_cents == 5_000
    wallet = get_balance(db, user.wallet_account_id)
    assert wallet.balance_cents == 5_000
    assert wallet.normal_side.value == "credit"
    assert wallet.currency == "KES"


def test_fee_split_keeps_three_legs_balanced(db: Session) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    post_entry(
        db,
        PostCommand(
            idempotency_key="fee-split-1",
            description="Collection with fee",
            postings=(
                PostingLine(MPESA_FLOAT.id, Direction.DEBIT, 10_000),
                PostingLine(user.wallet_account_id, Direction.CREDIT, 9_900),
                PostingLine(FEES.id, Direction.CREDIT, 100),
            ),
        ),
    )
    assert get_balance(db, MPESA_FLOAT.id).balance_cents == 10_000
    assert get_balance(db, user.wallet_account_id).balance_cents == 9_900
    assert get_balance(db, FEES.id).balance_cents == 100


def test_week1_does_not_enforce_spend_limits(db: Session) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    post_entry(
        db,
        PostCommand(
            idempotency_key="overdraw-1",
            description="Overdraw is visible until transfer rules exist",
            postings=(
                PostingLine(user.wallet_account_id, Direction.DEBIT, 100),
                PostingLine(SUSPENSE.id, Direction.CREDIT, 100),
            ),
        ),
    )
    assert get_balance(db, user.wallet_account_id).balance_cents == -100
    assert get_balance(db, SUSPENSE.id).balance_cents == 100


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, InvalidAmount),
        (-50, InvalidAmount),
        (True, InvalidAmount),
        (1.5, InvalidAmount),
    ],
)
def test_rejects_non_positive_integer_cents(db: Session, amount: object, expected: type) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    command = PostCommand(
        idempotency_key="bad-amount",
        description="Bad amount",
        postings=(
            PostingLine(MPESA_FLOAT.id, Direction.DEBIT, amount),  # type: ignore[arg-type]
            PostingLine(user.wallet_account_id, Direction.CREDIT, amount),  # type: ignore[arg-type]
        ),
    )
    with pytest.raises(expected):
        post_entry(db, command)
    assert _count(db, JournalEntry) == 0


def test_rejects_unbalanced_and_single_posting(db: Session) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    with pytest.raises(UnbalancedEntry):
        post_entry(
            db,
            PostCommand(
                idempotency_key="unbalanced",
                description="Unbalanced",
                postings=(
                    PostingLine(MPESA_FLOAT.id, Direction.DEBIT, 100),
                    PostingLine(user.wallet_account_id, Direction.CREDIT, 90),
                ),
            ),
        )
    with pytest.raises(UnbalancedEntry):
        post_entry(
            db,
            PostCommand(
                idempotency_key="one-leg",
                description="One leg",
                postings=(PostingLine(MPESA_FLOAT.id, Direction.DEBIT, 100),),
            ),
        )
    with pytest.raises(InvalidJournal):
        post_entry(
            db,
            PostCommand(idempotency_key="no-description", description="  ", postings=()),
        )
    assert _count(db, JournalEntry) == 0


def test_unknown_account_writes_nothing(db: Session) -> None:
    missing = uuid4()
    with pytest.raises(AccountNotFound):
        post_entry(
            db,
            PostCommand(
                idempotency_key="missing-account",
                description="Missing account",
                postings=(
                    PostingLine(MPESA_FLOAT.id, Direction.DEBIT, 100),
                    PostingLine(missing, Direction.CREDIT, 100),
                ),
            ),
        )
    assert _count(db, JournalEntry) == 0
    assert get_balance(db, MPESA_FLOAT.id).balance_cents == 0


def test_idempotent_replay_posts_once_including_reordered_lines(db: Session) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    first = post_entry(db, _command(user.wallet_account_id, key="  replay-1  "))
    second = post_entry(db, _command(user.wallet_account_id, key="replay-1", reverse=True))
    assert first.created is True
    assert second.created is False
    assert first.entry_id == second.entry_id
    assert _count(db, JournalEntry) == 1
    assert _count(db, Posting) == 2
    assert get_balance(db, user.wallet_account_id).balance_cents == 5_000


def test_same_key_with_a_different_body_conflicts(db: Session) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    post_entry(db, _command(user.wallet_account_id, key="once"))
    with pytest.raises(IdempotencyConflict):
        post_entry(db, _command(user.wallet_account_id, key="once", external_ref="receipt"))
    with pytest.raises(IdempotencyConflict):
        post_entry(db, _command(user.wallet_account_id, key="once", amount=4_000))
    assert get_balance(db, user.wallet_account_id).balance_cents == 5_000
    assert _count(db, JournalEntry) == 1


def test_postings_and_entries_are_immutable(db: Session, engine) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    post_entry(db, _command(user.wallet_account_id))
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE postings SET amount_cents = amount_cents + 1"))
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM postings"))
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE journal_entries SET description = 'rewritten'"))
    assert get_balance(db, user.wallet_account_id).balance_cents == 5_000
    description = db.scalar(select(JournalEntry.description))
    assert description == "Float to wallet"


def test_accounts_are_immutable(engine) -> None:
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE ledger_accounts SET name = 'renamed' WHERE code = 'system:mpesa_float'"
                )
            )
    with engine.connect() as conn:
        name = conn.execute(
            text("SELECT name FROM ledger_accounts WHERE code = 'system:mpesa_float'")
        ).scalar_one()
    assert name == "M-PESA float"


def test_database_rejects_unbalanced_and_orphan_entries(engine) -> None:
    entry_id = uuid4()
    with pytest.raises(IntegrityError, match="unbalanced"):
        with engine.begin() as conn:
            _insert_journal(conn, entry_id, "raw-unbalanced")
            _insert_pair(conn, entry_id, debit=100, credit=40)
    with pytest.raises(IntegrityError, match="unbalanced"):
        with engine.begin() as conn:
            _insert_journal(conn, uuid4(), "raw-orphan")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM journal_entries")).scalar_one() == 0


def test_database_accepts_a_balanced_raw_insert(engine) -> None:
    entry_id = uuid4()
    with engine.begin() as conn:
        _insert_journal(conn, entry_id, "raw-balanced")
        _insert_pair(conn, entry_id, debit=2_500, credit=2_500)
    with Session(engine) as session:
        assert get_balance(session, MPESA_FLOAT.id).balance_cents == 2_500
        assert get_balance(session, SUSPENSE.id).balance_cents == 2_500


def test_database_rejects_non_positive_posting_amount(engine) -> None:
    entry_id = uuid4()
    with pytest.raises(IntegrityError, match="ck_postings_amount_positive"):
        with engine.begin() as conn:
            _insert_journal(conn, entry_id, "raw-zero")
            _insert_pair(conn, entry_id, debit=0, credit=0)


def test_database_rejects_inconsistent_normal_side(engine) -> None:
    with pytest.raises(IntegrityError, match="ck_ledger_accounts_normal_side"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ledger_accounts
                      (id, code, name, account_type, normal_side, currency)
                    VALUES
                      (CAST(:id AS uuid), 'system:bad', 'Bad', 'asset', 'credit', 'KES')
                    """
                ),
                {"id": str(uuid4())},
            )


def test_balances_are_not_a_stored_column(engine) -> None:
    with engine.connect() as conn:
        columns = (
            conn.execute(
                text(
                    """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'ledger_accounts'
                """
                )
            )
            .scalars()
            .all()
        )
    assert "balance" not in columns
    assert "balance_cents" not in columns


def _insert_journal(conn, entry_id, key: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO journal_entries (id, idempotency_key, request_hash, description)
            VALUES (CAST(:id AS uuid), :key, :hash, 'raw')
            """
        ),
        {"id": str(entry_id), "key": key, "hash": "ab" * 32},
    )


def _insert_pair(conn, entry_id, *, debit: int, credit: int) -> None:
    conn.execute(
        text(
            """
            INSERT INTO postings
              (id, journal_entry_id, account_id, line_no, direction, amount_cents)
            VALUES
              (CAST(:debit_id AS uuid), CAST(:entry_id AS uuid), CAST(:float_id AS uuid),
               1, 'debit', :debit),
              (CAST(:credit_id AS uuid), CAST(:entry_id AS uuid), CAST(:suspense_id AS uuid),
               2, 'credit', :credit)
            """
        ),
        {
            "debit_id": str(uuid4()),
            "credit_id": str(uuid4()),
            "entry_id": str(entry_id),
            "float_id": str(MPESA_FLOAT.id),
            "suspense_id": str(SUSPENSE.id),
            "debit": debit,
            "credit": credit,
        },
    )
