"""B2C cash-outs: hold, outbox send, settle or release, timeouts leave the hold."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xmoney.errors import InsufficientFunds, ProviderError
from xmoney.history.service import ItemKind, wallet_history
from xmoney.identity.service import RegisteredUser, register_user
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import get_balance, post_entry
from xmoney.ledger.system import MPESA_CLEARING, MPESA_FLOAT
from xmoney.payments.cashouts import (
    handle_b2c_callback,
    resolve_cashout,
    result_url,
    start_cashout,
    timeout_url,
)
from xmoney.payments.daraja import DarajaHttpProvider, parse_b2c_result
from xmoney.payments.daraja_mock import DarajaMockState, create_daraja_mock_app
from xmoney.payments.deps import Rails
from xmoney.payments.jobs import send_due
from xmoney.payments.models import B2cCallbackLog, CallbackDisposition, Cashout, CashoutStatus
from xmoney.payments.provider import (
    AccessToken,
    B2cAccepted,
    B2cPaymentRequest,
    B2cResult,
    StkCallback,
    StkPushAccepted,
    StkPushRequest,
    StkQueryResult,
)

AMOUNT = 50_000


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
    from xmoney.payments.deps import get_rails

    app.dependency_overrides[get_rails] = lambda: Rails.of(rail[1])
    return client


class ScriptedB2c:
    name = "scripted"

    def __init__(self) -> None:
        self.pay_error: Exception | None = None
        self.payments = 0

    def obtain_token(self) -> AccessToken:
        return AccessToken(token="scripted", expires_in=3599)

    def stk_push(self, request: StkPushRequest) -> StkPushAccepted:
        raise RuntimeError("scripted B2C rail is B2C-only")

    def stk_query(self, checkout_request_id: str) -> StkQueryResult:
        raise RuntimeError("scripted B2C rail is B2C-only")

    def parse_stk_callback(self, payload: object) -> StkCallback:
        raise RuntimeError("scripted B2C rail is B2C-only")

    def b2c_payment(self, request: B2cPaymentRequest) -> B2cAccepted:
        self.payments += 1
        if self.pay_error is not None:
            raise self.pay_error
        return B2cAccepted(
            conversation_id=f"AG_{request.originator_conversation_id[:12]}",
            originator_conversation_id=request.originator_conversation_id,
            response_code="0",
            response_description="Accept the service request successfully.",
        )

    def parse_b2c_result(self, payload: object) -> B2cResult:
        return parse_b2c_result(payload)


def _credit(session: Session, wallet_id: UUID, cents: int, key: str) -> None:
    post_entry(
        session,
        PostCommand(
            idempotency_key=key,
            description="Test credit",
            postings=(
                PostingLine(MPESA_FLOAT.id, Direction.DEBIT, cents),
                PostingLine(wallet_id, Direction.CREDIT, cents),
            ),
        ),
    )


def _user(db: Session, handle: str = "amina", phone: str = "+254712345000") -> RegisteredUser:
    user = register_user(db, handle=handle, phone=phone, pin="2580")
    _credit(db, user.wallet_account_id, AMOUNT, f"credit:{handle}")
    return user


def _result(
    originator: str,
    *,
    code: int = 0,
    conversation: str = "AG_1",
    shillings: int = AMOUNT // 100,
    receipt: str = "SBOXCASH01",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ResultType": 0,
        "ResultCode": code,
        "ResultDesc": "ok" if code == 0 else "not paid",
        "OriginatorConversationID": originator,
        "ConversationID": conversation,
        "TransactionID": receipt if code == 0 else "",
    }
    if code == 0:
        result["ResultParameters"] = {
            "ResultParameter": [
                {"Key": "TransactionAmount", "Value": shillings},
                {"Key": "TransactionReceipt", "Value": receipt},
            ]
        }
    return {"Result": result}


def test_hold_then_success_settles_float(
    db: Session, rail: tuple[DarajaMockState, DarajaHttpProvider]
) -> None:
    user = _user(db)
    provider = rail[1]
    view = start_cashout(
        db,
        provider,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key="c-1",
    )
    assert view.status is CashoutStatus.INITIATED
    assert get_balance(db, user.wallet_account_id).balance_cents == 0
    assert get_balance(db, MPESA_CLEARING.id).balance_cents == -AMOUNT

    send_due(db, provider)
    cashout = db.get(Cashout, view.id, populate_existing=True)
    assert cashout is not None
    originator = cashout.originator_conversation_id
    conversation = cashout.conversation_id
    assert cashout.status == CashoutStatus.PENDING
    assert conversation

    disposition = handle_b2c_callback(
        db, provider, _result(originator, conversation=conversation), timed_out=False
    )
    assert disposition is CallbackDisposition.APPLIED
    db.expire_all()
    done = db.get(Cashout, view.id)
    assert done is not None
    assert done.status == CashoutStatus.SUCCEEDED
    assert done.mpesa_receipt_number == "SBOXCASH01"
    assert get_balance(db, user.wallet_account_id).balance_cents == 0
    assert get_balance(db, MPESA_CLEARING.id).balance_cents == 0
    assert get_balance(db, MPESA_FLOAT.id).balance_cents == 0
    history = wallet_history(
        db, user_id=user.id, wallet_account_id=user.wallet_account_id, limit=10
    )
    assert history.items[0].kind is ItemKind.CASHOUT
    assert history.items[0].amount_cents == -AMOUNT
    assert history.items[0].mpesa_receipt == "SBOXCASH01"


def test_failure_releases_the_hold(
    db: Session, rail: tuple[DarajaMockState, DarajaHttpProvider]
) -> None:
    user = _user(db, phone="+254712345001")
    provider = rail[1]
    view = start_cashout(
        db,
        provider,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key="c-fail",
    )
    send_due(db, provider)
    cashout = db.get(Cashout, view.id, populate_existing=True)
    assert cashout is not None
    handle_b2c_callback(
        db,
        provider,
        _result(
            cashout.originator_conversation_id,
            code=1,
            conversation=cashout.conversation_id or "AG_x",
        ),
        timed_out=False,
    )
    db.expire_all()
    done = db.get(Cashout, view.id)
    assert done is not None and done.status == CashoutStatus.FAILED
    assert get_balance(db, user.wallet_account_id).balance_cents == AMOUNT
    assert get_balance(db, MPESA_CLEARING.id).balance_cents == 0


def test_timeout_expires_and_leaves_the_hold(
    db: Session, rail: tuple[DarajaMockState, DarajaHttpProvider]
) -> None:
    user = _user(db, phone="+254712345037")
    provider = rail[1]
    view = start_cashout(
        db,
        provider,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key="c-to",
    )
    send_due(db, provider)
    cashout = db.get(Cashout, view.id, populate_existing=True)
    assert cashout is not None
    handle_b2c_callback(
        db,
        provider,
        _result(
            cashout.originator_conversation_id,
            code=1037,
            conversation=cashout.conversation_id or "AG_t",
        ),
        timed_out=True,
    )
    db.expire_all()
    done = db.get(Cashout, view.id)
    assert done is not None and done.status == CashoutStatus.EXPIRED
    assert get_balance(db, user.wallet_account_id).balance_cents == 0
    assert get_balance(db, MPESA_CLEARING.id).balance_cents == -AMOUNT


def test_late_success_after_timeout_settles(
    db: Session, rail: tuple[DarajaMockState, DarajaHttpProvider]
) -> None:
    user = _user(db)
    provider = rail[1]
    view = start_cashout(
        db,
        provider,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key="c-late",
    )
    send_due(db, provider)
    cashout = db.get(Cashout, view.id, populate_existing=True)
    assert cashout is not None
    originator = cashout.originator_conversation_id
    conversation = cashout.conversation_id or "AG_late"
    handle_b2c_callback(
        db, provider, _result(originator, code=1037, conversation=conversation), timed_out=True
    )
    handle_b2c_callback(
        db, provider, _result(originator, conversation=conversation), timed_out=False
    )
    db.expire_all()
    done = db.get(Cashout, view.id)
    assert done is not None and done.status == CashoutStatus.SUCCEEDED
    assert get_balance(db, MPESA_CLEARING.id).balance_cents == 0
    assert get_balance(db, user.wallet_account_id).balance_cents == 0


def test_duplicate_success_does_not_double_settle(
    db: Session, rail: tuple[DarajaMockState, DarajaHttpProvider]
) -> None:
    user = _user(db)
    provider = rail[1]
    view = start_cashout(
        db,
        provider,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key="c-dup",
    )
    send_due(db, provider)
    cashout = db.get(Cashout, view.id, populate_existing=True)
    assert cashout is not None
    payload = _result(
        cashout.originator_conversation_id, conversation=cashout.conversation_id or "AG_d"
    )
    assert (
        handle_b2c_callback(db, provider, payload, timed_out=False) is CallbackDisposition.APPLIED
    )
    assert (
        handle_b2c_callback(db, provider, payload, timed_out=False) is CallbackDisposition.DUPLICATE
    )
    n = db.scalar(select(func.count()).select_from(B2cCallbackLog))
    assert n == 2
    assert get_balance(db, MPESA_FLOAT.id).balance_cents == 0


def test_insufficient_funds_creates_no_row(
    db: Session, rail: tuple[DarajaMockState, DarajaHttpProvider]
) -> None:
    user = register_user(db, handle="broke", phone="+254712345000", pin="2580")
    with pytest.raises(InsufficientFunds):
        start_cashout(
            db,
            rail[1],
            user_id=user.id,
            wallet_account_id=user.wallet_account_id,
            phone=user.phone_e164,
            amount_cents=AMOUNT,
            idempotency_key="c-nf",
        )
    assert db.scalars(select(Cashout)).all() == []


def test_rail_4xx_releases_the_hold(db: Session) -> None:
    user = _user(db)
    rail = ScriptedB2c()
    rail.pay_error = ProviderError("B2C payment was rejected", status_code=400)
    view = start_cashout(
        db,
        rail,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key="c-4xx",
    )
    send_due(db, rail)
    db.expire_all()
    done = db.get(Cashout, view.id)
    assert done is not None and done.status == CashoutStatus.FAILED
    assert get_balance(db, user.wallet_account_id).balance_cents == AMOUNT


def test_initiated_expire_releases(db: Session) -> None:
    user = _user(db)
    rail = ScriptedB2c()
    view = start_cashout(
        db,
        rail,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key="c-exp",
    )
    later = datetime.now(UTC) + timedelta(seconds=301)
    resolve_cashout(db, view.id, now=later)
    db.expire_all()
    done = db.get(Cashout, view.id)
    assert done is not None and done.status == CashoutStatus.FAILED
    assert get_balance(db, user.wallet_account_id).balance_cents == AMOUNT


def test_http_cashout_and_wrong_token(
    api: TestClient,
    db: Session,
    sign_up,
    rail: tuple[DarajaMockState, DarajaHttpProvider],
) -> None:
    me = sign_up("amina", "+254712345000")
    _credit(db, UUID(me["wallet_account_id"]), AMOUNT, "http-credit")
    created = api.post(
        "/v1/cashouts",
        json={"amount_cents": AMOUNT},
        headers={"Idempotency-Key": "http-c"},
    )
    assert created.status_code == 201, created.text
    send_due(db, rail[1])
    fetched = api.get(f"/v1/cashouts/{created.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] in {"initiated", "pending", "succeeded"}
    bogus = api.post("/v1/payments/b2c/result/not-the-token", json={"Result": {}})
    assert bogus.status_code == 404


def test_idempotent_replay(db: Session, rail: tuple[DarajaMockState, DarajaHttpProvider]) -> None:
    user = _user(db)
    first = start_cashout(
        db,
        rail[1],
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key="same",
    )
    second = start_cashout(
        db,
        rail[1],
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key="same",
    )
    assert first.id == second.id
    assert second.idempotent_replay
    assert get_balance(db, user.wallet_account_id).balance_cents == 0


def test_callback_urls_share_the_stk_token() -> None:
    result = urlparse(result_url())
    timeout = urlparse(timeout_url())
    assert "/payments/b2c/result/" in result.path
    assert "/payments/b2c/timeout/" in timeout.path
    assert result.path.rsplit("/", 1)[-1] == timeout.path.rsplit("/", 1)[-1]
