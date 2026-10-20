"""Reversals post a compensating entry; large ones need a second actor."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from xmoney.errors import InsufficientFunds, InvalidReversal
from xmoney.identity.service import register_user
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import get_balance, post_entry
from xmoney.ledger.system import MPESA_FLOAT
from xmoney.reversals.service import approve_reversal, propose_reversal, reject_reversal
from xmoney.transfers.models import Transfer
from xmoney.transfers.service import send


def _fund(session: Session, wallet_id: UUID, cents: int, key: str) -> None:
    post_entry(
        session,
        PostCommand(
            idempotency_key=key,
            description="Test top-up",
            postings=(
                PostingLine(MPESA_FLOAT.id, Direction.DEBIT, cents),
                PostingLine(wallet_id, Direction.CREDIT, cents),
            ),
        ),
    )


def test_a_small_reversal_posts_immediately(db: Session) -> None:
    amina = register_user(db, handle="amina", phone="+254712345678")
    baraka = register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 5_000, "fund")
    sent = send(
        db,
        sender_user_id=amina.id,
        sender_handle=amina.handle,
        sender_wallet_id=amina.wallet_account_id,
        to_handle="baraka",
        amount_cents=400,
        idempotency_key="s1",
    )
    transfer = db.get(Transfer, sent.id)
    assert transfer is not None
    view = propose_reversal(
        db, original_journal_entry_id=transfer.journal_entry_id, reason="wrong payee", maker="alice"
    )
    assert view.status == "posted"
    assert view.needs_checker is False
    assert view.checker is None
    assert get_balance(db, amina.wallet_account_id).balance_cents == 5_000
    assert get_balance(db, baraka.wallet_account_id).balance_cents == 0


def test_a_large_reversal_needs_a_different_checker(db: Session, configure) -> None:
    configure(REVERSAL_MAKER_CHECKER_CENTS="1000")
    amina = register_user(db, handle="amina", phone="+254712345678")
    baraka = register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 50_000, "fund")
    sent = send(
        db,
        sender_user_id=amina.id,
        sender_handle=amina.handle,
        sender_wallet_id=amina.wallet_account_id,
        to_handle="baraka",
        amount_cents=20_000,
        idempotency_key="s1",
    )
    transfer = db.get(Transfer, sent.id)
    assert transfer is not None
    proposed = propose_reversal(
        db,
        original_journal_entry_id=transfer.journal_entry_id,
        reason="fraud",
        maker="alice",
    )
    assert proposed.status == "proposed"
    assert proposed.needs_checker is True
    assert get_balance(db, baraka.wallet_account_id).balance_cents == 20_000

    with pytest.raises(InvalidReversal, match="maker cannot approve"):
        approve_reversal(db, reversal_id=proposed.id, checker="alice")

    posted = approve_reversal(db, reversal_id=proposed.id, checker="bob")
    assert posted.status == "posted"
    assert posted.checker == "bob"
    assert get_balance(db, amina.wallet_account_id).balance_cents == 50_000
    assert get_balance(db, baraka.wallet_account_id).balance_cents == 0


def test_reject_leaves_the_original_entry(db: Session, configure) -> None:
    configure(REVERSAL_MAKER_CHECKER_CENTS="1000")
    amina = register_user(db, handle="amina", phone="+254712345678")
    baraka = register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 50_000, "fund")
    sent = send(
        db,
        sender_user_id=amina.id,
        sender_handle=amina.handle,
        sender_wallet_id=amina.wallet_account_id,
        to_handle="baraka",
        amount_cents=20_000,
        idempotency_key="s1",
    )
    transfer = db.get(Transfer, sent.id)
    assert transfer is not None
    proposed = propose_reversal(
        db, original_journal_entry_id=transfer.journal_entry_id, reason="maybe", maker="alice"
    )
    reject_reversal(db, reversal_id=proposed.id, checker="bob", reason="keep it")
    assert get_balance(db, baraka.wallet_account_id).balance_cents == 20_000
    again = propose_reversal(
        db, original_journal_entry_id=transfer.journal_entry_id, reason="retry", maker="alice"
    )
    assert again.status == "proposed"


def test_cannot_reverse_twice(db: Session) -> None:
    amina = register_user(db, handle="amina", phone="+254712345678")
    register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 5_000, "fund")
    sent = send(
        db,
        sender_user_id=amina.id,
        sender_handle=amina.handle,
        sender_wallet_id=amina.wallet_account_id,
        to_handle="baraka",
        amount_cents=400,
        idempotency_key="s1",
    )
    transfer = db.get(Transfer, sent.id)
    assert transfer is not None
    propose_reversal(
        db, original_journal_entry_id=transfer.journal_entry_id, reason="once", maker="alice"
    )
    with pytest.raises(InvalidReversal, match="already has"):
        propose_reversal(
            db, original_journal_entry_id=transfer.journal_entry_id, reason="twice", maker="bob"
        )


def test_reversal_refuses_to_overdraw_the_recipient(db: Session) -> None:
    amina = register_user(db, handle="amina", phone="+254712345678")
    baraka = register_user(db, handle="baraka", phone="+254722345678")
    wanjiku = register_user(db, handle="wanjiku", phone="+254733345678")
    _fund(db, amina.wallet_account_id, 5_000, "fund")
    sent = send(
        db,
        sender_user_id=amina.id,
        sender_handle=amina.handle,
        sender_wallet_id=amina.wallet_account_id,
        to_handle="baraka",
        amount_cents=400,
        idempotency_key="s1",
    )
    send(
        db,
        sender_user_id=baraka.id,
        sender_handle=baraka.handle,
        sender_wallet_id=baraka.wallet_account_id,
        to_handle="wanjiku",
        amount_cents=400,
        idempotency_key="s2",
    )
    transfer = db.get(Transfer, sent.id)
    assert transfer is not None
    with pytest.raises(InsufficientFunds):
        propose_reversal(
            db,
            original_journal_entry_id=transfer.journal_entry_id,
            reason="too late",
            maker="alice",
        )
    assert get_balance(db, wanjiku.wallet_account_id).balance_cents == 400
