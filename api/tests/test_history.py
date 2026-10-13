"""Transaction history: owner-only, newest first, cursor pages without gaps or repeats."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from xmoney.history.service import decode_cursor
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import post_entry, post_entry_in_transaction
from xmoney.ledger.system import MPESA_FLOAT
from xmoney.payments.daraja import DarajaHttpProvider
from xmoney.payments.daraja_mock import DarajaMockState, create_daraja_mock_app
from xmoney.payments.topups import callback_url


def _credit(wallet_id: UUID, cents: int, key: str) -> PostCommand:
    return PostCommand(
        idempotency_key=key,
        description="Test credit",
        postings=(
            PostingLine(MPESA_FLOAT.id, Direction.DEBIT, cents),
            PostingLine(wallet_id, Direction.CREDIT, cents),
        ),
    )


def _fund(db: Session, wallet: str, count: int, prefix: str) -> list[str]:
    return [
        str(post_entry(db, _credit(UUID(wallet), 100 + n, f"{prefix}-{n}")).entry_id)
        for n in range(count)
    ]


def _walk(http: TestClient, limit: int) -> tuple[list[str], int]:
    """Follow next_cursor to the end. Returns item ids and the number of pages."""
    ids: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        page = http.get("/v1/me/transactions", params=params)
        assert page.status_code == 200, page.text
        body = page.json()
        pages += 1
        assert len(body["items"]) <= limit
        ids.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return ids, pages


@pytest.fixture
def rail(client: TestClient) -> Iterator[DarajaMockState]:
    from xmoney.main import app
    from xmoney.payments.deps import get_payments_provider

    state = DarajaMockState()
    mock = TestClient(create_daraja_mock_app(state))
    provider = DarajaHttpProvider(
        base_url="http://testserver",
        consumer_key="sandbox",
        consumer_secret="sandbox",
        shortcode="174379",
        passkey="sandbox-passkey",
        client=mock,
    )
    app.dependency_overrides[get_payments_provider] = lambda: provider
    try:
        yield state
    finally:
        mock.close()


def test_history_shows_top_ups_and_sends_to_their_owner_only(
    client: TestClient, rail: DarajaMockState, sign_up
) -> None:
    from xmoney.main import app

    sign_up("amina", "+254712345678")
    topup = client.post(
        "/v1/topups", json={"amount_cents": 50_000}, headers={"Idempotency-Key": "t1"}
    )
    assert topup.status_code == 201, topup.text
    [attempt] = rail.attempts
    assert client.post(urlparse(callback_url()).path, json=attempt.payload).status_code == 200
    receipt = client.get(f"/v1/topups/{topup.json()['id']}").json()["mpesa_receipt_number"]

    with TestClient(app) as baraka, TestClient(app) as otieno:
        sign_up("baraka", "+254722345678", http=baraka)
        sign_up("otieno", "+254733345678", http=otieno)
        sent = client.post(
            "/v1/transfers",
            json={"to": "@baraka", "amount_cents": 20_000, "note": "Lunch"},
            headers={"Idempotency-Key": "s1"},
        )
        assert sent.status_code == 201, sent.text
        back = baraka.post(
            "/v1/transfers",
            json={"to": "@amina", "amount_cents": 5_000},
            headers={"Idempotency-Key": "s2"},
        )
        assert back.status_code == 201, back.text

        mine = client.get("/v1/me/transactions").json()
        assert mine["next_cursor"] is None
        assert [
            (i["kind"], i["amount_cents"], i["counterparty"], i["note"], i["mpesa_receipt"])
            for i in mine["items"]
        ] == [
            ("transfer_in", 5_000, "baraka", None, None),
            ("transfer_out", -20_000, "baraka", "Lunch", None),
            ("topup", 50_000, None, None, receipt),
        ]

        theirs = baraka.get("/v1/me/transactions").json()["items"]
        assert [(i["kind"], i["amount_cents"], i["counterparty"]) for i in theirs] == [
            ("transfer_out", -5_000, "amina"),
            ("transfer_in", 20_000, "amina"),
        ]
        assert otieno.get("/v1/me/transactions").json() == {"items": [], "next_cursor": None}

    client.post("/v1/auth/sign-out")
    anonymous = client.get("/v1/me/transactions")
    assert anonymous.status_code == 401
    assert anonymous.json()["error"] == "not_authenticated"


@pytest.mark.parametrize(("count", "limit"), [(25, 7), (21, 7), (1, 20), (0, 20)])
def test_pages_cover_every_item_once_in_order(
    client: TestClient, sign_up, db: Session, count: int, limit: int
) -> None:
    me = sign_up("amina", "+254712345678")
    posted = _fund(db, me["wallet_account_id"], count, "fund")

    ids, pages = _walk(client, limit)
    assert ids == list(reversed(posted))
    assert pages == max(1, -(-count // limit))


def test_entries_from_one_transaction_share_a_timestamp_and_still_page(
    client: TestClient, sign_up, db: Session
) -> None:
    me = sign_up("amina", "+254712345678")
    wallet = UUID(me["wallet_account_id"])
    db.rollback()
    with db.begin():
        posted = {
            str(post_entry_in_transaction(db, _credit(wallet, 100, f"tie-{n}")).entry_id)
            for n in range(5)
        }

    first = client.get("/v1/me/transactions", params={"limit": 2}).json()
    assert len({item["created_at"] for item in first["items"]}) == 1
    ids, pages = _walk(client, 2)
    assert set(ids) == posted
    assert len(ids) == 5
    assert pages == 3


def test_items_posted_between_pages_do_not_shift_later_pages(
    client: TestClient, sign_up, db: Session
) -> None:
    me = sign_up("amina", "+254712345678")
    older = _fund(db, me["wallet_account_id"], 6, "old")

    first = client.get("/v1/me/transactions", params={"limit": 3}).json()
    assert [i["id"] for i in first["items"]] == older[:2:-1]
    newer = _fund(db, me["wallet_account_id"], 2, "new")

    rest = client.get(
        "/v1/me/transactions", params={"limit": 3, "cursor": first["next_cursor"]}
    ).json()
    assert [i["id"] for i in rest["items"]] == older[2::-1]
    assert rest["next_cursor"] is None

    top = client.get("/v1/me/transactions", params={"limit": 2}).json()
    assert [i["id"] for i in top["items"]] == list(reversed(newer))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "%%%",
        _b64(b"\xff\xfe"),
        _b64(b"no-separator"),
        _b64(b"yesterday|00000000-0000-4000-8000-000000000001"),
        _b64(b"2026-10-13T10:00:00+00:00|not-a-uuid"),
        _b64(b"2026-10-13T10:00:00|00000000-0000-4000-8000-000000000001"),
    ],
)
def test_a_cursor_this_api_did_not_issue_is_rejected(
    client: TestClient, sign_up, cursor: str
) -> None:
    sign_up("amina", "+254712345678")
    response = client.get("/v1/me/transactions", params={"cursor": cursor})
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "invalid_cursor"


@pytest.mark.parametrize("limit", ["0", "101", "ten"])
def test_limit_must_be_between_1_and_100(client: TestClient, sign_up, limit: str) -> None:
    sign_up("amina", "+254712345678")
    assert client.get("/v1/me/transactions", params={"limit": limit}).status_code == 422


def test_cursors_round_trip_microseconds(client: TestClient, sign_up, db: Session) -> None:
    me = sign_up("amina", "+254712345678")
    posted = _fund(db, me["wallet_account_id"], 2, "fund")
    first = client.get("/v1/me/transactions", params={"limit": 1}).json()
    assert decode_cursor(first["next_cursor"]) == (
        datetime.fromisoformat(first["items"][0]["created_at"]),
        UUID(posted[1]),
    )
