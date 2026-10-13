"""Nothing on the open demo can mint money or change the mock for other visitors."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from xmoney.config import Settings
from xmoney.ledger.service import get_balance
from xmoney.ledger.system import MPESA_FLOAT


def _credit(wallet: str, key: str = "mint-1") -> dict[str, object]:
    return {
        "idempotency_key": key,
        "description": "Free money",
        "postings": [
            {"account_id": str(MPESA_FLOAT.id), "direction": "debit", "amount_cents": 10_000_00},
            {"account_id": wallet, "direction": "credit", "amount_cents": 10_000_00},
        ],
    }


def test_journal_route_is_off_by_default(client, sign_up, db) -> None:
    me = sign_up("amina", "+254712345678")
    response = client.post("/v1/sandbox/journal-entries", json=_credit(me["wallet_account_id"]))
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert get_balance(db, UUID(me["wallet_account_id"])).balance_cents == 0


def test_journal_route_is_off_for_anonymous_callers_too(client) -> None:
    response = client.post("/v1/sandbox/journal-entries", json=_credit(str(MPESA_FLOAT.id)))
    assert response.status_code == 404


def test_journal_flag_cannot_be_on_behind_a_public_https_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SANDBOX_JOURNAL_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://d111111abcdef8.cloudfront.net/api")
    with pytest.raises(ValidationError, match="SANDBOX_JOURNAL_ENABLED is for local development"):
        Settings()


def test_journal_flag_is_allowed_on_a_laptop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_JOURNAL_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    assert Settings().sandbox_journal_enabled is True


def test_mock_control_route_can_be_turned_off(client, configure) -> None:
    configure(DARAJA_MOCK_CONTROL_ENABLED="false")
    response = client.put("/sandbox/daraja/__control/behavior", json={"outcome": "cancelled"})
    assert response.status_code == 404
    health = client.get("/sandbox/daraja/__control/health").json()
    assert health["outcome"] == "success"


def test_top_ups_respect_the_demo_cap(client, sign_up, configure) -> None:
    configure(TOPUP_MAX_CENTS=str(1_000_00))
    sign_up("amina", "+254712345678")
    response = client.post(
        "/v1/topups", json={"amount_cents": 1_001_00}, headers={"Idempotency-Key": "big-1"}
    )
    assert response.status_code == 422
    assert response.json()["message"] == "a top-up cannot exceed KES 1,000"


def test_the_demo_cap_cannot_exceed_the_hard_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOPUP_MAX_CENTS", str(250_001 * 100))
    with pytest.raises(ValidationError):
        Settings()
