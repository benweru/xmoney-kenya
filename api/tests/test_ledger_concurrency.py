"""Concurrent posts must not double-apply an idempotency key or drop a transfer."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xmoney.identity.service import register_user
from xmoney.ledger.models import JournalEntry
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import get_balance, post_entry
from xmoney.ledger.system import MPESA_FLOAT


def _command(wallet_id, *, key: str, amount: int) -> PostCommand:
    return PostCommand(
        idempotency_key=key,
        description="Concurrent transfer",
        postings=(
            PostingLine(MPESA_FLOAT.id, Direction.DEBIT, amount),
            PostingLine(wallet_id, Direction.CREDIT, amount),
        ),
    )


def test_concurrent_distinct_posts_sum_balances(engine) -> None:
    with Session(engine) as session:
        user = register_user(session, handle="amina", phone="+254712345678")
        wallet_id = user.wallet_account_id
    workers = 12
    barrier = threading.Barrier(workers)

    def worker(index: int) -> None:
        barrier.wait(timeout=5)
        session = Session(engine)
        try:
            post_entry(session, _command(wallet_id, key=f"concurrent-{index}", amount=100))
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(worker, range(workers)))

    with Session(engine) as session:
        assert get_balance(session, wallet_id).balance_cents == workers * 100
        assert get_balance(session, MPESA_FLOAT.id).balance_cents == workers * 100
        count = session.scalar(select(func.count()).select_from(JournalEntry))
        assert count == workers


def test_concurrent_same_idempotency_key_posts_once(engine) -> None:
    with Session(engine) as session:
        user = register_user(session, handle="amina", phone="+254712345678")
        wallet_id = user.wallet_account_id
    workers = 10
    barrier = threading.Barrier(workers)
    command = _command(wallet_id, key="same-key", amount=100)

    def worker(_: int) -> tuple[bool, str]:
        barrier.wait(timeout=5)
        session = Session(engine)
        try:
            result = post_entry(session, command)
            return result.created, str(result.entry_id)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(worker, range(workers)))

    created = [flag for flag, _entry_id in results]
    entry_ids = {entry_id for _flag, entry_id in results}
    assert created.count(True) == 1
    assert len(entry_ids) == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(JournalEntry)) == 1
        assert get_balance(session, wallet_id).balance_cents == 100
