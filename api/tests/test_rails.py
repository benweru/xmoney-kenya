"""Visitors choose the mock or the Daraja sandbox, and each top-up stays on its rail."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from xmoney.config import Settings
from xmoney.errors import RailUnavailable
from xmoney.identity.service import register_user
from xmoney.payments.daraja import parse_stk_callback
from xmoney.payments.deps import Rails, build_rails
from xmoney.payments.models import Topup
from xmoney.payments.provider import (
    AccessToken,
    StkCallback,
    StkPushAccepted,
    StkPushRequest,
    StkQueryResult,
)
from xmoney.payments.topups import callback_url, resolve_stale_topups, start_topup

SANDBOX_KEYS = {
    "DARAJA_CONSUMER_KEY": "portal-key",
    "DARAJA_CONSUMER_SECRET": "portal-secret",
    "DARAJA_PASSKEY": "portal-passkey",
}


class CountingRail:
    def __init__(self, name: str) -> None:
        self.name = name
        self.pushes: list[StkPushRequest] = []
        self.queries = 0

    def obtain_token(self) -> AccessToken:
        return AccessToken(token="t", expires_in=3599)

    def stk_push(self, request: StkPushRequest) -> StkPushAccepted:
        self.pushes.append(request)
        return StkPushAccepted(
            merchant_request_id="m",
            checkout_request_id=f"ws_CO_{self.name}_{len(self.pushes)}",
            response_code="0",
            response_description="ok",
            customer_message="ok",
        )

    def stk_query(self, checkout_request_id: str) -> StkQueryResult:
        self.queries += 1
        return StkQueryResult(checkout_request_id, False, 1032, "cancelled", None)

    def parse_stk_callback(self, payload: object) -> StkCallback:
        return parse_stk_callback(payload)


def test_the_mock_is_the_only_rail_by_default(client) -> None:
    body = client.get("/v1/payment-rails").json()
    assert body == {
        "default": "mock",
        "rails": [{"name": "mock", "label": "Daraja mock", "restricted": False}],
    }


def test_the_sandbox_rail_needs_portal_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_RAILS", '["mock", "sandbox"]')
    with pytest.raises(ValidationError, match="needs DARAJA_CONSUMER_KEY"):
        Settings()


def test_a_public_demo_must_restrict_the_sandbox_rail(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in SANDBOX_KEYS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PAYMENT_RAILS", '["mock", "sandbox"]')
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://d111111abcdef8.cloudfront.net/api")
    with pytest.raises(ValidationError, match="DARAJA_SANDBOX_ALLOWED_PHONES"):
        Settings()
    monkeypatch.setenv("DARAJA_SANDBOX_ALLOWED_PHONES", '["+254708374149"]')
    assert Settings().payment_rails == ["mock", "sandbox"]


def test_allowed_phones_must_be_e164(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARAJA_SANDBOX_ALLOWED_PHONES", '["0708374149"]')
    with pytest.raises(ValidationError, match="DARAJA_SANDBOX_ALLOWED_PHONES"):
        Settings()


def test_rails_cannot_repeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_RAILS", '["mock", "mock"]')
    with pytest.raises(ValidationError, match="lists a rail twice"):
        Settings()


def test_the_mock_base_url_cannot_be_live_safaricom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARAJA_MOCK_BASE_URL", "https://api.safaricom.co.ke")
    with pytest.raises(ValidationError, match="refusing Safaricom host"):
        Settings()


def test_restricted_sandbox_rail_refuses_other_phones(client, configure, sign_up) -> None:
    configure(
        PAYMENT_RAILS='["mock", "sandbox"]',
        DARAJA_SANDBOX_ALLOWED_PHONES='["+254708374149"]',
        **SANDBOX_KEYS,
    )
    rails = client.get("/v1/payment-rails").json()["rails"]
    assert rails[1] == {"name": "sandbox", "label": "Safaricom Daraja sandbox", "restricted": True}

    sign_up("amina", "+254712345678")
    response = client.post(
        "/v1/topups",
        json={"amount_cents": 10_000, "rail": "sandbox"},
        headers={"Idempotency-Key": "t1"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "rail_unavailable"
    assert "test phones" in response.json()["message"]


def test_a_rail_that_is_not_offered_is_refused(client, sign_up) -> None:
    sign_up("amina", "+254712345678")
    response = client.post(
        "/v1/topups",
        json={"amount_cents": 10_000, "rail": "sandbox"},
        headers={"Idempotency-Key": "t1"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "rail_unavailable"


def test_allowed_phones_are_normalized(configure) -> None:
    configure(
        PAYMENT_RAILS='["sandbox", "mock"]',
        DARAJA_SANDBOX_ALLOWED_PHONES='["+254 708 374 149"]',
        **SANDBOX_KEYS,
    )
    rails = build_rails()
    try:
        assert rails.default == "sandbox"
        assert rails.for_new_topup(None, "+254708374149").name == "sandbox"
        with pytest.raises(RailUnavailable):
            rails.for_new_topup("sandbox", "+254712345678")
    finally:
        rails.close()


def test_each_top_up_is_queried_on_the_rail_that_took_it(db: Session) -> None:
    mock, sandbox = CountingRail("mock"), CountingRail("sandbox")
    rails = Rails.of(mock, sandbox)
    user = register_user(db, handle="amina", phone="+254712345678")
    view = start_topup(
        db,
        rails.for_new_topup("sandbox", user.phone_e164),
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=10_000,
        idempotency_key="k1",
    )
    assert view.rail == "sandbox"
    assert len(sandbox.pushes) == 1 and not mock.pushes

    topup = db.get(Topup, view.id)
    assert topup is not None
    later = topup.created_at + timedelta(seconds=61)
    assert resolve_stale_topups(db, rails, now=later) == 1
    assert (sandbox.queries, mock.queries) == (1, 0)


def test_a_top_up_on_a_rail_no_longer_offered_still_expires(db: Session) -> None:
    sandbox = CountingRail("sandbox")
    user = register_user(db, handle="amina", phone="+254712345678")
    view = start_topup(
        db,
        sandbox,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=10_000,
        idempotency_key="k1",
    )
    mock_only = Rails.of(CountingRail("mock"))
    topup = db.get(Topup, view.id)
    assert topup is not None
    assert resolve_stale_topups(db, mock_only, now=topup.created_at + timedelta(seconds=61)) == 0
    assert resolve_stale_topups(db, mock_only, now=topup.created_at + timedelta(seconds=301)) == 1
    db.refresh(topup)
    assert topup.status == "expired"
    assert sandbox.queries == 0


def test_mock_callbacks_can_stay_inside_the_task(configure) -> None:
    configure(
        PUBLIC_BASE_URL="https://d111111abcdef8.cloudfront.net/api",
        DARAJA_MOCK_CALLBACK_BASE_URL="http://127.0.0.1:8000",
        STK_CALLBACK_TOKEN="0123456789abcdef0123",
    )
    assert (
        callback_url("mock")
        == "http://127.0.0.1:8000/v1/payments/stk/callback/0123456789abcdef0123"
    )
    assert callback_url("sandbox").startswith("https://d111111abcdef8.cloudfront.net/api/v1/")
