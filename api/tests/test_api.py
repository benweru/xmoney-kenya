"""HTTP surface for health, handles, and the sandbox journal."""

from __future__ import annotations

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
    created = client.post("/v1/users", json={"handle": "@Amina", "phone": "+254712345678"})
    assert created.status_code == 201
    body = created.json()
    assert body["handle"] == "amina"
    assert body["phone"] == "+254712345678"
    assert body["wallet_account_id"]

    found = client.get("/v1/handles/AMINA")
    assert found.status_code == 200
    assert found.json() == {
        "handle": "amina",
        "user_id": body["id"],
        "wallet_account_id": body["wallet_account_id"],
    }
    assert "phone" not in found.json()

    encoded = client.get("/v1/handles/%40amina")
    assert encoded.status_code == 200
    assert encoded.json()["user_id"] == body["id"]

    missing = client.get("/v1/handles/otieno")
    assert missing.status_code == 404
    assert missing.json()["error"] == "handle_not_found"

    duplicate = client.post(
        "/v1/users",
        json={"handle": "amina", "phone": "+254700000000"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "handle_taken"


def test_invalid_phone_and_unknown_balance(client) -> None:
    rejected = client.post("/v1/users", json={"handle": "amina", "phone": "0712345678"})
    assert rejected.status_code == 422
    assert rejected.json()["error"] == "invalid_phone"
    extra = client.post(
        "/v1/users",
        json={"handle": "amina", "phone": "+254712345678", "role": "admin"},
    )
    assert extra.status_code == 422
    missing = client.get("/v1/accounts/00000000-0000-4000-8000-000000000099/balance")
    assert missing.status_code == 404
    assert missing.json()["error"] == "account_not_found"


def test_sandbox_journal_is_idempotent(client) -> None:
    created = client.post("/v1/users", json={"handle": "amina", "phone": "+254712345678"})
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

    balance = client.get(f"/v1/accounts/{wallet}/balance")
    assert balance.status_code == 200
    assert balance.json()["balance_cents"] == 5000
    assert balance.json()["currency"] == "KES"
    float_balance = client.get(f"/v1/accounts/{MPESA_FLOAT.id}/balance")
    assert float_balance.json()["balance_cents"] == 5000


def test_sandbox_journal_rejects_coerced_amounts(client) -> None:
    created = client.post("/v1/users", json={"handle": "amina", "phone": "+254712345678"})
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
    assert client.get(f"/v1/accounts/{wallet}/balance").json()["balance_cents"] == 0
