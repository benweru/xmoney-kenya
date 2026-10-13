"""HTTP surface for health, handles, and the local-development journal."""

from __future__ import annotations

from uuid import UUID

from xmoney.ledger.service import get_balance
from xmoney.ledger.system import MPESA_FLOAT


def test_health_and_root_declare_the_sandbox(client) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "xmoney-kenya",
        "mode": "sandbox",
        "moves_real_money": False,
    }
    assert health.headers["X-Sandbox"] == "true"
    assert health.headers["X-Moves-Real-Money"] == "false"
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["moves_real_money"] is False
    assert "Central Bank of Kenya" in root.json()["notice"]


def test_register_and_lookup_round_trip(client) -> None:
    created = client.post(
        "/v1/users", json={"handle": "@Amina", "phone": "+254712345678", "pin": "2580"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["handle"] == "amina"
    assert body["phone"] == "+254712345678"
    assert body["wallet_account_id"]

    found = client.get("/v1/handles/AMINA")
    assert found.status_code == 200
    assert found.json() == {"handle": "amina"}

    encoded = client.get("/v1/handles/%40amina")
    assert encoded.status_code == 200
    assert encoded.json() == {"handle": "amina"}

    missing = client.get("/v1/handles/otieno")
    assert missing.status_code == 404
    assert missing.json()["error"] == "handle_not_found"

    duplicate = client.post(
        "/v1/users",
        json={"handle": "amina", "phone": "+254700000000", "pin": "2580"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "handle_taken"


def test_invalid_phone_and_unknown_balance(client) -> None:
    rejected = client.post(
        "/v1/users", json={"handle": "amina", "phone": "0712345678", "pin": "2580"}
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"] == "invalid_phone"
    extra = client.post(
        "/v1/users",
        json={"handle": "amina", "phone": "+254712345678", "pin": "2580", "role": "admin"},
    )
    assert extra.status_code == 422
    anonymous = client.get("/v1/accounts/00000000-0000-4000-8000-000000000099/balance")
    assert anonymous.status_code == 401
    assert anonymous.json()["error"] == "not_authenticated"


def test_sandbox_journal_is_idempotent(client, db, configure) -> None:
    configure(SANDBOX_JOURNAL_ENABLED="true")
    created = client.post(
        "/v1/users", json={"handle": "amina", "phone": "+254712345678", "pin": "2580"}
    )
    wallet = created.json()["wallet_account_id"]
    payload = {
        "idempotency_key": "api-demo-1",
        "description": "Sandbox demonstration",
        "postings": [
            {
                "account_id": str(MPESA_FLOAT.id),
                "direction": "debit",
                "amount_cents": 5000,
            },
            {"account_id": wallet, "direction": "credit", "amount_cents": 5000},
        ],
    }
    first = client.post("/v1/sandbox/journal-entries", json=payload)
    assert first.status_code == 201
    assert first.json()["idempotent_replay"] is False
    assert [line["amount_cents"] for line in first.json()["postings"]] == [5000, 5000]

    replay = client.post("/v1/sandbox/journal-entries", json=payload)
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["idempotent_replay"] is True

    conflict = client.post(
        "/v1/sandbox/journal-entries",
        json={**payload, "description": "A different body"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "idempotency_conflict"

    assert get_balance(db, UUID(wallet)).balance_cents == 5000
    assert get_balance(db, MPESA_FLOAT.id).balance_cents == 5000


def test_sandbox_journal_rejects_coerced_amounts(client, db, configure) -> None:
    configure(SANDBOX_JOURNAL_ENABLED="true")
    created = client.post(
        "/v1/users", json={"handle": "amina", "phone": "+254712345678", "pin": "2580"}
    )
    wallet = created.json()["wallet_account_id"]
    for amount in (5000.0, "5000"):
        response = client.post(
            "/v1/sandbox/journal-entries",
            json={
                "idempotency_key": f"coerced-{type(amount).__name__}",
                "description": "Coerced amount",
                "postings": [
                    {"account_id": str(MPESA_FLOAT.id), "direction": "debit", "amount_cents": 5000},
                    {"account_id": wallet, "direction": "credit", "amount_cents": amount},
                ],
            },
        )
        assert response.status_code == 422, amount
    assert get_balance(db, UUID(wallet)).balance_cents == 0
