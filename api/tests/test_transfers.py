"""Send by @handle: no overdrafts, idempotent, and safe under concurrent sends."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from xmoney.errors import IdempotencyConflict, InsufficientFunds, InvalidTransfer
from xmoney.identity.service import RegisteredUser, register_user
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import get_balance, post_entry
from xmoney.ledger.system import MPESA_FLOAT
from xmoney.transfers.models import Transfer
from xmoney.transfers.service import TransferView, send


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


def _pair(session: Session) -> tuple[RegisteredUser, RegisteredUser]:
    amina = register_user(session, handle="amina", phone="+254712345678")
    baraka = register_user(session, handle="baraka", phone="+254722345678")
    return amina, baraka


def _send(
    session: Session,
    sender: RegisteredUser,
    to: str,
    cents: int,
    key: str,
    note: str | None = None,
) -> TransferView:
    return send(
        session,
        sender_user_id=sender.id,
        sender_handle=sender.handle,
        sender_wallet_id=sender.wallet_account_id,
        to_handle=to,
        amount_cents=cents,
        idempotency_key=key,
        note=note,
    )


def _balance(session: Session, user: RegisteredUser) -> int:
    session.rollback()
    return get_balance(session, user.wallet_account_id).balance_cents


def test_send_over_http(client: TestClient, sign_up, db: Session) -> None:
    me = sign_up("amina", "+254712345678")
    from xmoney.main import app

    with TestClient(app) as other:
        sign_up("baraka", "+254722345678", http=other)
    _fund(db, UUID(me["wallet_account_id"]), 1_000, "fund-1")

    def post(body: dict[str, Any], key: str | None = "k1") -> Any:
        headers = {"Idempotency-Key": key} if key else {}
        return client.post("/v1/transfers", json=body, headers=headers)

    sent = post({"to": "@Baraka", "amount_cents": 400, "note": "  lunch   money "})
    assert sent.status_code == 201, sent.text
    assert sent.json()["sender"] == "amina"
    assert sent.json()["recipient"] == "baraka"
    assert sent.json()["note"] == "lunch money"

    replay = post({"to": "@Baraka", "amount_cents": 400, "note": "lunch money"})
    assert replay.status_code == 200
    assert replay.json()["id"] == sent.json()["id"]
    assert replay.json()["idempotent_replay"] is True

    assert post({"to": "baraka", "amount_cents": 500}).status_code == 409
    overdraft = post({"to": "baraka", "amount_cents": 601}, key="k2")
    assert overdraft.status_code == 422
    assert overdraft.json()["error"] == "insufficient_funds"
    assert post({"to": "amina", "amount_cents": 1}, key="k3").json()["error"] == "invalid_transfer"
    assert post({"to": "otieno", "amount_cents": 1}, key="k4").status_code == 404
    assert post({"to": "baraka", "amount_cents": 1.0}, key="k5").status_code == 422
    assert post({"to": "baraka", "amount_cents": 1}, key=None).status_code == 422

    balance = client.get(f"/v1/accounts/{me['wallet_account_id']}/balance").json()
    assert balance["balance_cents"] == 600


def test_sending_requires_a_session(client: TestClient) -> None:
    response = client.post(
        "/v1/transfers", json={"to": "baraka", "amount_cents": 1}, headers={"Idempotency-Key": "k"}
    )
    assert response.status_code == 401


def test_an_empty_wallet_cannot_send(db: Session) -> None:
    amina, baraka = _pair(db)
    with pytest.raises(InsufficientFunds):
        _send(db, amina, "baraka", 1, "k1")
    assert _balance(db, amina) == 0
    assert _balance(db, baraka) == 0
    assert db.scalar(select(func.count()).select_from(Transfer)) == 0


def test_the_whole_balance_can_be_sent(db: Session) -> None:
    amina, baraka = _pair(db)
    _fund(db, amina.wallet_account_id, 2_500, "fund-1")
    _send(db, amina, "baraka", 2_500, "k1")
    assert _balance(db, amina) == 0
    assert _balance(db, baraka) == 2_500


def test_a_refused_key_can_be_retried_after_a_top_up(db: Session) -> None:
    amina, baraka = _pair(db)
    with pytest.raises(InsufficientFunds):
        _send(db, amina, "baraka", 500, "k1")
    _fund(db, amina.wallet_account_id, 500, "fund-1")
    assert _send(db, amina, "baraka", 500, "k1").idempotent_replay is False
    assert _balance(db, baraka) == 500


def test_same_key_different_transfer_conflicts(db: Session) -> None:
    amina, baraka = _pair(db)
    _fund(db, amina.wallet_account_id, 1_000, "fund-1")
    _send(db, amina, "baraka", 100, "k1", note="rent")
    for args in ((200, "rent"), (100, "food")):
        with pytest.raises(IdempotencyConflict):
            _send(db, amina, "baraka", args[0], "k1", note=args[1])
    assert _balance(db, amina) == 900


def test_notes_are_bounded(db: Session) -> None:
    amina, _baraka = _pair(db)
    _fund(db, amina.wallet_account_id, 1_000, "fund-1")
    with pytest.raises(InvalidTransfer):
        _send(db, amina, "baraka", 1, "k1", note="x" * 141)
    assert _send(db, amina, "baraka", 1, "k2", note="   ").note is None


def test_100_concurrent_sends_never_overdraw(engine) -> None:
    with Session(engine) as session:
        amina, baraka = _pair(session)
        _fund(session, amina.wallet_account_id, 50 * 100, "fund-1")
    workers = 100
    barrier = threading.Barrier(workers)

    def attempt(index: int) -> str:
        barrier.wait(timeout=10)
        with Session(engine) as session:
            try:
                _send(session, amina, "baraka", 100, f"send-{index}")
            except InsufficientFunds:
                return "refused"
        return "sent"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(attempt, range(workers)))

    assert results.count("sent") == 50
    assert results.count("refused") == 50
    with Session(engine) as session:
        assert _balance(session, amina) == 0
        assert _balance(session, baraka) == 50 * 100
        assert session.scalar(select(func.count()).select_from(Transfer)) == 50


def test_opposite_concurrent_sends_do_not_deadlock(engine) -> None:
    with Session(engine) as session:
        amina, baraka = _pair(session)
        _fund(session, amina.wallet_account_id, 10_000, "fund-a")
        _fund(session, baraka.wallet_account_id, 10_000, "fund-b")
    workers = 40
    barrier = threading.Barrier(workers)

    def attempt(index: int) -> None:
        sender, to = (amina, "baraka") if index % 2 == 0 else (baraka, "amina")
        barrier.wait(timeout=10)
        with Session(engine) as session:
            _send(session, sender, to, 100 + index, f"swap-{index}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(attempt, range(workers)))

    sent_by_amina = sum(100 + i for i in range(0, workers, 2))
    sent_by_baraka = sum(100 + i for i in range(1, workers, 2))
    with Session(engine) as session:
        assert _balance(session, amina) == 10_000 - sent_by_amina + sent_by_baraka
        assert _balance(session, baraka) == 10_000 - sent_by_baraka + sent_by_amina
        assert session.scalar(select(func.count()).select_from(Transfer)) == workers


def test_concurrent_replays_of_one_key_send_once(engine) -> None:
    with Session(engine) as session:
        amina, baraka = _pair(session)
        _fund(session, amina.wallet_account_id, 1_000, "fund-1")
    workers = 10
    barrier = threading.Barrier(workers)

    def attempt(_: int) -> str:
        barrier.wait(timeout=10)
        with Session(engine) as session:
            return str(_send(session, amina, "baraka", 300, "same-key").id)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        ids = set(pool.map(attempt, range(workers)))

    assert len(ids) == 1
    with Session(engine) as session:
        assert _balance(session, amina) == 700
        assert session.scalar(select(func.count()).select_from(Transfer)) == 1


def test_transfers_are_immutable(db: Session) -> None:
    amina, _baraka = _pair(db)
    _fund(db, amina.wallet_account_id, 1_000, "fund-1")
    _send(db, amina, "baraka", 100, "k1")
    db.rollback()
    for statement in ("UPDATE transfers SET amount_cents = 1", "DELETE FROM transfers"):
        with pytest.raises(DBAPIError, match="immutable"):
            with db.begin():
                db.execute(text(statement))
        db.rollback()
