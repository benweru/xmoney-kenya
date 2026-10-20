"""P2P fee schedules: bands, a free allowance, and a three-leg journal entry."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from xmoney.errors import InsufficientFunds
from xmoney.identity.service import register_user
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import get_balance, post_entry
from xmoney.ledger.system import FEES, MPESA_FLOAT
from xmoney.transfers.fees import (
    fee_for_amount,
    parse_bands,
    publish_p2p_schedule,
    quote_p2p,
    round_half_up,
)
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


def _send(session: Session, sender, to: str, cents: int, key: str):
    return send(
        session,
        sender_user_id=sender.id,
        sender_handle=sender.handle,
        sender_wallet_id=sender.wallet_account_id,
        to_handle=to,
        amount_cents=cents,
        idempotency_key=key,
    )


def test_round_half_up() -> None:
    assert round_half_up(0, 10_000) == 0
    assert round_half_up(4_999, 10_000) == 0
    assert round_half_up(5_000, 10_000) == 1
    assert round_half_up(15_000, 10_000) == 2


def test_default_bands_price_the_demo_tariff() -> None:
    bands = parse_bands(
        [
            {"up_to_cents": 10_000, "flat_cents": 0, "rate_bps": 0},
            {"up_to_cents": 100_000, "flat_cents": 100, "rate_bps": 0},
            {"up_to_cents": None, "flat_cents": 200, "rate_bps": 50},
        ]
    )
    assert fee_for_amount(bands, 1) == 0
    assert fee_for_amount(bands, 10_000) == 0
    assert fee_for_amount(bands, 10_001) == 100
    assert fee_for_amount(bands, 100_000) == 100
    assert fee_for_amount(bands, 100_001) == 200 + 500
    assert fee_for_amount(bands, 200_000) == 200 + 1_000


def test_a_send_under_kes_100_is_free(db: Session) -> None:
    amina = register_user(db, handle="amina", phone="+254712345678")
    baraka = register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 5_000, "fund")
    view = _send(db, amina, "baraka", 2_500, "k1")
    assert view.fee_cents == 0
    assert view.fee_schedule_version == 1
    assert get_balance(db, amina.wallet_account_id).balance_cents == 2_500
    assert get_balance(db, baraka.wallet_account_id).balance_cents == 2_500
    assert get_balance(db, FEES.id).balance_cents == 0


def test_a_mid_band_send_posts_three_legs(db: Session) -> None:
    amina = register_user(db, handle="amina", phone="+254712345678")
    baraka = register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 50_000, "fund")
    view = _send(db, amina, "baraka", 20_000, "k1")
    assert view.fee_cents == 100
    assert get_balance(db, amina.wallet_account_id).balance_cents == 29_900
    assert get_balance(db, baraka.wallet_account_id).balance_cents == 20_000
    assert get_balance(db, FEES.id).balance_cents == 100


def test_percent_band_rounds_half_up(db: Session) -> None:
    amina = register_user(db, handle="amina", phone="+254712345678")
    register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 200_000, "fund")
    view = _send(db, amina, "baraka", 120_000, "k1")
    assert view.fee_cents == 800
    assert get_balance(db, FEES.id).balance_cents == 800


def test_quote_matches_the_send(db: Session) -> None:
    amina = register_user(db, handle="amina", phone="+254712345678")
    register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 50_000, "fund")
    quoted = quote_p2p(db, sender_user_id=amina.id, amount_cents=20_000)
    sent = _send(db, amina, "baraka", 20_000, "k1")
    assert sent.fee_cents == quoted.fee_cents == 100
    assert sent.fee_schedule_version == quoted.schedule_version


def test_a_free_allowance_waives_the_first_sends(db: Session) -> None:
    publish_p2p_schedule(
        db,
        bands=[
            {"up_to_cents": 10_000, "flat_cents": 0, "rate_bps": 0},
            {"up_to_cents": None, "flat_cents": 250, "rate_bps": 0},
        ],
        free_count_per_calendar_month=2,
    )
    amina = register_user(db, handle="amina", phone="+254712345678")
    register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 80_000, "fund")
    first = _send(db, amina, "baraka", 20_000, "k1")
    second = _send(db, amina, "baraka", 20_000, "k2")
    third = _send(db, amina, "baraka", 20_000, "k3")
    assert first.fee_cents == 0
    assert second.fee_cents == 0
    assert third.fee_cents == 250
    assert third.fee_schedule_version == 2
    assert get_balance(db, FEES.id).balance_cents == 250


def test_amount_plus_fee_must_fit(db: Session) -> None:
    amina = register_user(db, handle="amina", phone="+254712345678")
    register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 20_050, "fund")
    with pytest.raises(InsufficientFunds, match="plus KES 1.00 fee"):
        _send(db, amina, "baraka", 20_000, "k1")
    assert get_balance(db, amina.wallet_account_id).balance_cents == 20_050
    assert db.scalar(select(func.count()).select_from(Transfer)) == 0


def test_quote_over_http(client: TestClient, sign_up, db: Session) -> None:
    me = sign_up("amina", "+254712345678")
    quoted = client.get("/v1/transfers/quote", params={"amount_cents": 20_000})
    assert quoted.status_code == 200, quoted.text
    body = quoted.json()
    assert body["amount_cents"] == 20_000
    assert body["fee_cents"] == 100
    assert body["total_cents"] == 20_100
    assert body["fee_schedule_version"] == 1
    assert body["waived"] is False
    assert me["handle"] == "amina"


def test_replay_keeps_the_fee_that_was_charged(db: Session) -> None:
    amina = register_user(db, handle="amina", phone="+254712345678")
    register_user(db, handle="baraka", phone="+254722345678")
    _fund(db, amina.wallet_account_id, 50_000, "fund")
    first = _send(db, amina, "baraka", 20_000, "same")
    replay = _send(db, amina, "baraka", 20_000, "same")
    assert replay.idempotent_replay is True
    assert replay.fee_cents == first.fee_cents == 100
    assert get_balance(db, FEES.id).balance_cents == 100


def test_fee_schedules_are_immutable(db: Session) -> None:
    db.rollback()
    with pytest.raises(DBAPIError, match="immutable"):
        with db.begin():
            db.execute(text("UPDATE fee_schedules SET version = 99"))
    db.rollback()
