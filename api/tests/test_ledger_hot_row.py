"""System accounts are not global locks; wallet running totals match postings."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from xmoney.identity.service import register_user
from xmoney.ledger.models import LedgerAccount
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import get_balance, post_entry, post_entry_in_transaction, trial_totals
from xmoney.ledger.system import MPESA_FLOAT, SYSTEM_ACCOUNTS


def _credit(wallet_id, *, key: str, amount: int = 1_000) -> PostCommand:
    return PostCommand(
        idempotency_key=key,
        description="hot-row top-up",
        postings=(
            PostingLine(MPESA_FLOAT.id, Direction.DEBIT, amount),
            PostingLine(wallet_id, Direction.CREDIT, amount),
        ),
    )


def test_system_accounts_allow_negative_wallets_do_not(db: Session) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    for spec in SYSTEM_ACCOUNTS:
        row = db.get(LedgerAccount, spec.id)
        assert row is not None and row.allow_negative is True
    wallet = db.get(LedgerAccount, user.wallet_account_id)
    assert wallet is not None and wallet.allow_negative is False


def test_wallet_running_totals_match_postings(db: Session) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    post_entry(db, _credit(user.wallet_account_id, key="a", amount=2_000))
    post_entry(db, _credit(user.wallet_account_id, key="b", amount=3_000))
    wallet = db.get(LedgerAccount, user.wallet_account_id)
    assert wallet is not None
    db.refresh(wallet)
    assert wallet.running_debit_cents == 0
    assert wallet.running_credit_cents == 5_000
    assert get_balance(db, user.wallet_account_id).balance_cents == 5_000
    float_row = db.get(LedgerAccount, MPESA_FLOAT.id)
    assert float_row is not None
    db.refresh(float_row)
    assert float_row.running_debit_cents == 0
    assert float_row.running_credit_cents == 0
    assert get_balance(db, MPESA_FLOAT.id).balance_cents == 5_000
    debits, credits = trial_totals(db)
    assert debits == credits == 5_000


def test_uncommitted_float_post_does_not_block_another_wallet(engine) -> None:
    """Holding a top-up open must not take FOR UPDATE on mpesa_float."""
    with Session(engine) as setup:
        first = register_user(setup, handle="amina", phone="+254712345678")
        second = register_user(setup, handle="baraka", phone="+254722345678")
        first_wallet, second_wallet = first.wallet_account_id, second.wallet_account_id

    s1 = Session(engine)
    s1.begin()
    try:
        post_entry_in_transaction(s1, _credit(first_wallet, key="open-amina", amount=100))
        with Session(engine) as s2:
            s2.execute(text("SET lock_timeout = '800ms'"))
            post_entry(s2, _credit(second_wallet, key="baraka-while-open", amount=100))
            assert get_balance(s2, second_wallet).balance_cents == 100
    finally:
        s1.rollback()
        s1.close()


def test_running_columns_are_not_writable_from_sql(engine) -> None:
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE ledger_accounts SET running_debit_cents = 1 "
                    "WHERE code = 'system:mpesa_float'"
                )
            )
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE ledger_accounts SET name = 'x' WHERE code = 'system:mpesa_float'")
            )
