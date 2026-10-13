"""STK top-ups: the state machine, exactly-once callbacks, and STK Query fallback."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from xmoney.errors import ProviderError
from xmoney.identity.service import RegisteredUser, register_user
from xmoney.ledger.models import JournalEntry
from xmoney.ledger.service import get_balance
from xmoney.ledger.system import MPESA_FLOAT
from xmoney.payments.daraja import DarajaHttpProvider, parse_stk_callback
from xmoney.payments.daraja_mock import Behavior, DarajaMockState, create_daraja_mock_app
from xmoney.payments.models import StkCallbackLog, Topup, TopupStatus
from xmoney.payments.provider import (
    AccessToken,
    StkCallback,
    StkPushAccepted,
    StkPushRequest,
    StkQueryResult,
)
from xmoney.payments.topups import (
    TopupView,
    callback_url,
    handle_stk_callback,
    resolve_stale_topups,
    resolve_topup,
    start_topup,
)

AMOUNT = 50_000


def _callback_path() -> str:
    return urlparse(callback_url()).path


@pytest.fixture
def rail() -> Iterator[tuple[DarajaMockState, DarajaHttpProvider]]:
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
    try:
        yield state, provider
    finally:
        mock.close()


@pytest.fixture
def api(client: TestClient, rail: tuple[DarajaMockState, DarajaHttpProvider]) -> TestClient:
    from xmoney.main import app
    from xmoney.payments.deps import get_payments_provider

    app.dependency_overrides[get_payments_provider] = lambda: rail[1]
    return client


class ScriptedRail:
    """A rail whose push, query, and errors are set by the test."""

    name = "scripted"

    def __init__(self) -> None:
        self.push_error: Exception | None = None
        self.query_result: StkQueryResult | None = None
        self.before_push_returns: Callable[[StkPushAccepted], None] | None = None
        self.pushes = 0
        self.queries = 0

    def obtain_token(self) -> AccessToken:
        return AccessToken(token="scripted", expires_in=3599)

    def stk_push(self, request: StkPushRequest) -> StkPushAccepted:
        self.pushes += 1
        if self.push_error is not None:
            raise self.push_error
        accepted = StkPushAccepted(
            merchant_request_id="m-1",
            checkout_request_id=f"ws_CO_{request.idempotency_key.split(':')[1][:12]}",
            response_code="0",
            response_description="Success. Request accepted for processing",
            customer_message="Success. Request accepted for processing",
        )
        if self.before_push_returns is not None:
            self.before_push_returns(accepted)
        return accepted

    def stk_query(self, checkout_request_id: str) -> StkQueryResult:
        self.queries += 1
        assert self.query_result is not None
        return self.query_result

    def parse_stk_callback(self, payload: object) -> StkCallback:
        return parse_stk_callback(payload)


def _callback(
    checkout: str, *, code: int = 0, shillings: int = AMOUNT // 100, receipt: str = "SBOXTEST0001"
) -> dict[str, Any]:
    callback: dict[str, Any] = {
        "MerchantRequestID": "m-1",
        "CheckoutRequestID": checkout,
        "ResultCode": code,
        "ResultDesc": "ok" if code == 0 else "not paid",
    }
    if code == 0:
        callback["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": shillings},
                {"Name": "MpesaReceiptNumber", "Value": receipt},
                {"Name": "PhoneNumber", "Value": 254712345678},
            ]
        }
    return {"Body": {"stkCallback": callback}}


def _user(db: Session, phone: str = "+254712345678") -> RegisteredUser:
    return register_user(db, handle="amina", phone=phone)


def _start(db: Session, provider: Any, user: RegisteredUser, *, key: str = "k1") -> TopupView:
    return start_topup(
        db,
        provider,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key=key,
    )


def _wallet(db: Session, user: RegisteredUser) -> int:
    db.rollback()
    return get_balance(db, user.wallet_account_id).balance_cents


def _dispositions(db: Session) -> list[str]:
    db.rollback()
    return list(
        db.scalars(select(StkCallbackLog.disposition).order_by(StkCallbackLog.received_at)).all()
    )


def _entries(db: Session) -> int:
    db.rollback()
    return db.scalar(select(func.count()).select_from(JournalEntry)) or 0


def _later(db: Session, topup_id: UUID, seconds: int) -> datetime:
    created = db.get(Topup, topup_id, populate_existing=True)
    assert created is not None
    return created.created_at + timedelta(seconds=seconds)


def test_top_up_over_http_credits_the_wallet_once(api: TestClient, rail, sign_up) -> None:
    state, _provider = rail
    me = sign_up("amina", "+254712345000")
    created = api.post(
        "/v1/topups", json={"amount_cents": AMOUNT}, headers={"Idempotency-Key": "k1"}
    )
    assert created.status_code == 201, created.text
    topup = created.json()
    assert topup["status"] == "pending"
    assert topup["phone"] == "+254712345000"

    [attempt] = state.attempts
    for _ in range(2):
        ack = api.post(_callback_path(), json=attempt.payload)
        assert ack.json() == {"ResultCode": 0, "ResultDesc": "Accepted"}

    done = api.get(f"/v1/topups/{topup['id']}").json()
    assert done["status"] == "succeeded"
    assert done["mpesa_receipt_number"].startswith("SBOX")
    balance = api.get(f"/v1/accounts/{me['wallet_account_id']}/balance").json()
    assert balance["balance_cents"] == AMOUNT
    float_balance = api.get(f"/v1/accounts/{MPESA_FLOAT.id}/balance").json()
    assert float_balance["balance_cents"] == AMOUNT

    replay = api.post(
        "/v1/topups", json={"amount_cents": AMOUNT}, headers={"Idempotency-Key": "k1"}
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == topup["id"]
    assert replay.json()["idempotent_replay"] is True
    assert len(state.records_by_checkout) == 1

    reused = api.post(
        "/v1/topups", json={"amount_cents": 60_000}, headers={"Idempotency-Key": "k1"}
    )
    assert reused.status_code == 409
    assert reused.json()["error"] == "idempotency_conflict"


def test_top_ups_need_a_session_a_key_and_whole_shillings(api: TestClient, sign_up) -> None:
    assert (
        api.post(
            "/v1/topups", json={"amount_cents": AMOUNT}, headers={"Idempotency-Key": "k"}
        ).status_code
        == 401
    )
    sign_up("amina", "+254712345000")
    assert api.post("/v1/topups", json={"amount_cents": AMOUNT}).status_code == 422
    for amount in (150, 100.0, "100", 0, 25_000_100):
        response = api.post(
            "/v1/topups", json={"amount_cents": amount}, headers={"Idempotency-Key": "k"}
        )
        assert response.status_code == 422, amount


def test_a_top_up_is_visible_only_to_its_owner(api: TestClient, sign_up) -> None:
    sign_up("amina", "+254712345000")
    topup = api.post(
        "/v1/topups", json={"amount_cents": AMOUNT}, headers={"Idempotency-Key": "k1"}
    ).json()
    from xmoney.main import app

    with TestClient(app) as other:
        sign_up("baraka", "+254722345000", http=other)
        response = other.get(f"/v1/topups/{topup['id']}")
    assert response.status_code == 404
    assert response.json()["error"] == "topup_not_found"


def test_duplicate_callbacks_apply_once(db: Session, rail) -> None:
    state, provider = rail
    user = _user(db, "+254712345000")
    view = _start(db, provider, user)
    [attempt] = state.attempts
    for _ in range(3):
        handle_stk_callback(db, provider, attempt.payload)
    assert _dispositions(db) == ["applied", "duplicate", "duplicate"]
    assert _wallet(db, user) == AMOUNT
    assert _entries(db) == 1
    topup = db.get(Topup, view.id)
    assert topup is not None and topup.status == "succeeded"


def test_concurrent_duplicate_callbacks_apply_once(engine, rail) -> None:
    state, provider = rail
    with Session(engine) as session:
        user = _user(session, "+254712345000")
        _start(session, provider, user)
    [attempt] = state.attempts
    workers = 10
    barrier = threading.Barrier(workers)

    def deliver(_: int) -> str:
        barrier.wait(timeout=5)
        with Session(engine) as session:
            return handle_stk_callback(session, provider, attempt.payload).value

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(deliver, range(workers)))
    assert results.count("applied") == 1
    assert results.count("duplicate") == workers - 1
    with Session(engine) as session:
        assert _wallet(session, user) == AMOUNT
        assert _entries(session) == 1


@pytest.mark.parametrize(("suffix", "code"), [("032", 1032), ("037", 1037), ("001", 1)])
def test_failed_payments_move_no_money(db: Session, rail, suffix: str, code: int) -> None:
    state, provider = rail
    user = _user(db, f"+254712345{suffix}")
    view = _start(db, provider, user)
    [attempt] = state.attempts
    handle_stk_callback(db, provider, attempt.payload)
    topup = db.get(Topup, view.id, populate_existing=True)
    assert topup is not None
    assert topup.status == "failed"
    assert topup.result_code == code
    assert topup.journal_entry_id is None
    assert _wallet(db, user) == 0
    assert _entries(db) == 0


def test_a_dropped_callback_is_recovered_with_stk_query(db: Session, rail) -> None:
    state, provider = rail
    user = _user(db, "+254712345099")
    view = _start(db, provider, user)
    [attempt] = state.attempts
    assert attempt.dropped

    early = resolve_topup(db, provider, view.id, now=_later(db, view.id, 30))
    assert early.status == "pending"
    resolved = resolve_topup(db, provider, view.id, now=_later(db, view.id, 61))
    assert resolved.status == "succeeded"
    assert resolved.mpesa_receipt_number is None
    assert _wallet(db, user) == AMOUNT

    handle_stk_callback(db, provider, attempt.payload)
    topup = db.get(Topup, view.id, populate_existing=True)
    assert topup is not None
    assert topup.mpesa_receipt_number is not None
    assert _dispositions(db) == ["duplicate"]
    assert _wallet(db, user) == AMOUNT


def test_a_silent_push_expires_and_a_late_success_still_credits(db: Session, rail) -> None:
    state, provider = rail
    state.default_behavior = Behavior(delay_ms=10_000, drop_callback=True)
    user = _user(db)
    view = _start(db, provider, user)

    assert resolve_topup(db, provider, view.id, now=_later(db, view.id, 61)).status == "pending"
    expired = resolve_topup(db, provider, view.id, now=_later(db, view.id, 301))
    assert expired.status == "expired"
    assert _wallet(db, user) == 0

    [attempt] = state.attempts
    assert handle_stk_callback(db, provider, attempt.payload).value == "applied"
    topup = db.get(Topup, view.id, populate_existing=True)
    assert topup is not None and topup.status == "succeeded"
    assert _wallet(db, user) == AMOUNT


def test_a_callback_that_beats_the_push_response_is_applied(db: Session, engine) -> None:
    rail = ScriptedRail()

    def callback_arrives_first(accepted: StkPushAccepted) -> None:
        with Session(engine) as other:
            payload = _callback(accepted.checkout_request_id)
            assert handle_stk_callback(other, rail, payload).value == "unmatched"

    rail.before_push_returns = callback_arrives_first
    user = _user(db)
    view = _start(db, rail, user)
    assert view.status is TopupStatus.SUCCEEDED
    assert view.mpesa_receipt_number == "SBOXTEST0001"
    assert _dispositions(db) == ["applied"]
    assert _wallet(db, user) == AMOUNT


def test_a_contradicting_late_callback_is_logged_not_applied(db: Session) -> None:
    rail = ScriptedRail()
    user = _user(db)
    view = _start(db, rail, user)
    assert view.checkout_request_id is not None
    rail.query_result = StkQueryResult(
        checkout_request_id=view.checkout_request_id,
        processing=False,
        result_code=0,
        result_desc="The service request is processed successfully.",
        outcome=None,
    )
    assert resolve_topup(db, rail, view.id, now=_later(db, view.id, 61)).status == "succeeded"
    disposition = handle_stk_callback(db, rail, _callback(view.checkout_request_id, code=1032))
    assert disposition.value == "conflict"
    assert _wallet(db, user) == AMOUNT


def test_a_callback_for_the_wrong_amount_is_held(db: Session) -> None:
    rail = ScriptedRail()
    user = _user(db)
    view = _start(db, rail, user)
    assert view.checkout_request_id is not None
    payload = _callback(view.checkout_request_id, shillings=AMOUNT // 100 - 1)
    assert handle_stk_callback(db, rail, payload).value == "amount_mismatch"
    topup = db.get(Topup, view.id, populate_existing=True)
    assert topup is not None and topup.status == "pending"
    assert _wallet(db, user) == 0


def test_an_unknown_callback_is_acknowledged_and_logged(api: TestClient) -> None:
    ack = api.post(_callback_path(), json=_callback("ws_CO_unknown"))
    assert ack.status_code == 200
    assert ack.json()["ResultCode"] == 0
    bad = api.post(_callback_path(), json={"Body": {}})
    assert bad.status_code == 422


def test_a_callback_without_the_secret_token_is_ignored(api: TestClient, rail, sign_up) -> None:
    state, _provider = rail
    me = sign_up("amina", "+254712345000")
    topup = api.post(
        "/v1/topups", json={"amount_cents": AMOUNT}, headers={"Idempotency-Key": "k1"}
    ).json()
    forged = _callback(topup["checkout_request_id"])
    for path in ("/v1/payments/stk/callback/" + "0" * 32, "/v1/payments/stk/callback"):
        assert api.post(path, json=forged).status_code in (404, 405)
    assert api.get(f"/v1/topups/{topup['id']}").json()["status"] == "pending"
    balance = api.get(f"/v1/accounts/{me['wallet_account_id']}/balance").json()
    assert balance["balance_cents"] == 0


def test_a_refused_push_fails_the_top_up(db: Session) -> None:
    rail = ScriptedRail()
    rail.push_error = ProviderError("Invalid Access Token", status_code=401)
    user = _user(db)
    view = _start(db, rail, user)
    assert view.status is TopupStatus.FAILED
    assert view.result_desc == "Invalid Access Token"


def test_an_unanswered_push_can_be_retried_with_the_same_key(db: Session) -> None:
    rail = ScriptedRail()
    rail.push_error = httpx.ConnectError("connection refused")
    user = _user(db)
    with pytest.raises(ProviderError):
        _start(db, rail, user)
    topup = db.scalar(select(Topup))
    assert topup is not None and topup.status == "initiated"

    rail.push_error = None
    retried = _start(db, rail, user)
    assert retried.id == topup.id
    assert retried.status is TopupStatus.PENDING
    assert rail.pushes == 2


def test_a_push_that_never_gets_through_expires(db: Session) -> None:
    rail = ScriptedRail()
    rail.push_error = httpx.ConnectError("connection refused")
    user = _user(db)
    with pytest.raises(ProviderError):
        _start(db, rail, user)
    topup = db.scalar(select(Topup))
    assert topup is not None
    expired = resolve_topup(db, rail, topup.id, now=_later(db, topup.id, 301))
    assert expired.status == "expired"


def test_the_database_enforces_the_state_machine(db: Session) -> None:
    rail = ScriptedRail()
    user = _user(db)
    view = _start(db, rail, user)
    assert view.checkout_request_id is not None
    handle_stk_callback(db, rail, _callback(view.checkout_request_id))
    db.rollback()
    for statement in (
        "UPDATE topups SET status = 'pending'",
        "UPDATE topups SET status = 'failed'",
        "UPDATE topups SET amount_cents = amount_cents + 100",
        "DELETE FROM topups",
    ):
        with pytest.raises(DBAPIError, match="top-up|immutable"):
            with db.begin():
                db.execute(text(statement))
        db.rollback()


def test_expired_top_ups_cannot_return_to_pending(db: Session) -> None:
    rail = ScriptedRail()
    user = _user(db)
    view = _start(db, rail, user)
    rail.query_result = StkQueryResult(view.checkout_request_id or "", True, None, "busy", None)
    assert resolve_topup(db, rail, view.id, now=_later(db, view.id, 301)).status == "expired"
    db.rollback()
    with pytest.raises(DBAPIError, match="illegal top-up transition"):
        with db.begin():
            db.execute(text("UPDATE topups SET status = 'pending'"))
    db.rollback()


def test_polling_does_not_hammer_stk_query(db: Session) -> None:
    rail = ScriptedRail()
    user = _user(db)
    view = _start(db, rail, user)
    rail.query_result = StkQueryResult(view.checkout_request_id or "", True, None, "busy", None)
    for seconds in (61, 64, 70, 75, 77):
        assert (
            resolve_topup(db, rail, view.id, now=_later(db, view.id, seconds)).status == "pending"
        )
    assert rail.queries == 2


def test_resolve_stale_topups_sweeps_only_waiting_ones(db: Session) -> None:
    rail = ScriptedRail()
    user = _user(db)
    waiting = _start(db, rail, user, key="waiting")
    done = _start(db, rail, user, key="done")
    assert done.checkout_request_id is not None
    handle_stk_callback(db, rail, _callback(done.checkout_request_id))
    rail.query_result = StkQueryResult(waiting.checkout_request_id or "", False, 1032, "no", None)
    assert resolve_stale_topups(db, rail, now=_later(db, waiting.id, 61)) == 1
    assert rail.queries == 1
    topup = db.get(Topup, waiting.id, populate_existing=True)
    assert topup is not None and topup.status == "failed"


def test_ids_and_times_are_recorded(db: Session) -> None:
    rail = ScriptedRail()
    user = _user(db)
    before = datetime.now(UTC)
    view = _start(db, rail, user)
    assert view.created_at >= before - timedelta(seconds=5)
    assert view.resolved_at is None
    assert view.checkout_request_id and view.checkout_request_id.startswith("ws_CO_")
