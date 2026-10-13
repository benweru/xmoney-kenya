"""Wallet balances are readable only by their signed-in owner."""

from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import post_entry
from xmoney.ledger.system import MPESA_FLOAT, SYSTEM_ACCOUNTS


def _fund(db: Session, wallet: str, cents: int) -> None:
    post_entry(
        db,
        PostCommand(
            idempotency_key=f"fund-{wallet}",
            description="Test top-up",
            postings=(
                PostingLine(MPESA_FLOAT.id, Direction.DEBIT, cents),
                PostingLine(UUID(wallet), Direction.CREDIT, cents),
            ),
        ),
    )


def test_owners_read_their_own_balance(client: TestClient, sign_up, db: Session) -> None:
    me = sign_up("amina", "+254712345678")
    _fund(db, me["wallet_account_id"], 1_500)
    mine = client.get("/v1/me/balance")
    assert mine.status_code == 200
    assert mine.json()["balance_cents"] == 1_500
    assert mine.json()["account_id"] == me["wallet_account_id"]
    by_id = client.get(f"/v1/accounts/{me['wallet_account_id']}/balance")
    assert by_id.json() == mine.json()


def test_other_wallets_and_system_accounts_look_missing(client: TestClient, sign_up) -> None:
    from xmoney.main import app

    me = sign_up("amina", "+254712345678")
    with TestClient(app) as other:
        theirs = sign_up("baraka", "+254722345678", http=other)
    unknown = "00000000-0000-4000-8000-000000000099"
    for account_id in [theirs["wallet_account_id"], unknown, *(a.id for a in SYSTEM_ACCOUNTS)]:
        response = client.get(f"/v1/accounts/{account_id}/balance")
        assert response.status_code == 404, account_id
        assert response.json()["error"] == "account_not_found"
    assert client.get(f"/v1/accounts/{me['wallet_account_id']}/balance").status_code == 200


def test_balances_need_a_session(client: TestClient, sign_up) -> None:
    me = sign_up("amina", "+254712345678")
    client.post("/v1/auth/sign-out")
    assert client.get("/v1/me/balance").status_code == 401
    assert client.get(f"/v1/accounts/{me['wallet_account_id']}/balance").status_code == 401


def test_handle_lookup_exposes_only_the_handle(client: TestClient, sign_up) -> None:
    sign_up("amina", "+254712345678")
    found = client.get("/v1/handles/@Amina")
    assert found.status_code == 200
    assert found.json() == {"handle": "amina"}
