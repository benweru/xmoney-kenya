"""Hypothesis properties for ledger invariants (M1 evidence, ≥200 examples each)."""

from __future__ import annotations

from uuid import uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xmoney.errors import InsufficientFunds
from xmoney.identity.service import register_user
from xmoney.ledger.models import Posting
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import get_balance, post_entry, trial_totals
from xmoney.ledger.system import MPESA_FLOAT
from xmoney.transfers.fees import quote_p2p
from xmoney.transfers.service import send

_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture, HealthCheck.too_slow),
)


def _person() -> tuple[str, str]:
    suffix = uuid4().hex[:8]
    return f"u{suffix}", f"+2547{uuid4().int % 10**8:08d}"


def _credit(wallet_id, *, key: str, amount: int) -> PostCommand:
    return PostCommand(
        idempotency_key=key,
        description="property top-up",
        postings=(
            PostingLine(MPESA_FLOAT.id, Direction.DEBIT, amount),
            PostingLine(wallet_id, Direction.CREDIT, amount),
        ),
    )


def _posting_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(Posting)) or 0)


@_SETTINGS
@given(amounts=st.lists(st.integers(min_value=1, max_value=50_000), min_size=1, max_size=12))
def test_random_topups_keep_debits_equal_credits(db: Session, amounts: list[int]) -> None:
    handle, phone = _person()
    user = register_user(db, handle=handle, phone=phone)
    for index, amount in enumerate(amounts):
        post_entry(
            db,
            _credit(user.wallet_account_id, key=f"topup-{uuid4()}-{index}", amount=amount),
        )
    debits, credits = trial_totals(db)
    assert debits == credits
    assert get_balance(db, user.wallet_account_id).balance_cents == sum(amounts)


@_SETTINGS
@given(
    funds=st.integers(min_value=1, max_value=20_000),
    attempts=st.lists(st.integers(min_value=1, max_value=25_000), min_size=1, max_size=15),
)
def test_sends_and_refusals_never_make_a_wallet_negative(
    db: Session, funds: int, attempts: list[int]
) -> None:
    sender = register_user(db, handle=_person()[0], phone=_person()[1])
    recipient = register_user(db, handle=_person()[0], phone=_person()[1])
    post_entry(db, _credit(sender.wallet_account_id, key=f"fund-{uuid4()}", amount=funds))

    remaining = funds
    received = 0
    for index, amount in enumerate(attempts):
        quote = quote_p2p(db, sender_user_id=sender.id, amount_cents=amount)
        try:
            send(
                db,
                sender_user_id=sender.id,
                sender_handle=sender.handle,
                sender_wallet_id=sender.wallet_account_id,
                to_handle=recipient.handle,
                amount_cents=amount,
                idempotency_key=f"send-{uuid4()}-{index}",
            )
        except InsufficientFunds:
            assert quote.total_cents > remaining
            continue
        remaining -= quote.total_cents
        received += amount
        assert remaining >= 0

    assert get_balance(db, sender.wallet_account_id).balance_cents == remaining
    assert remaining >= 0
    assert get_balance(db, recipient.wallet_account_id).balance_cents == received
    debits, credits = trial_totals(db)
    assert debits == credits


@_SETTINGS
@given(
    amount=st.integers(min_value=1, max_value=50_000),
    replays=st.integers(min_value=1, max_value=8),
)
def test_replaying_an_idempotency_key_never_adds_a_posting(
    db: Session, amount: int, replays: int
) -> None:
    user = register_user(db, handle=_person()[0], phone=_person()[1])
    key = f"replay-{uuid4()}"
    first = post_entry(db, _credit(user.wallet_account_id, key=key, amount=amount))
    after_first = _posting_count(db)
    assert first.created is True
    for _ in range(replays):
        again = post_entry(db, _credit(user.wallet_account_id, key=key, amount=amount))
        assert again.created is False
        assert again.entry_id == first.entry_id
    assert _posting_count(db) == after_first
    assert get_balance(db, user.wallet_account_id).balance_cents == amount
