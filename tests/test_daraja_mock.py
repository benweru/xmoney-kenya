"""Daraja mock: OAuth, STK push, scripted callbacks, and the provider adapter."""

from __future__ import annotations

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xmoney.errors import CallbackParseError, IdempotencyConflict, InvalidAmount, SandboxViolation
from xmoney.ledger.models import Posting
from xmoney.main import app
from xmoney.payments.daraja import DarajaHttpProvider, daraja_password, parse_stk_callback
from xmoney.payments.provider import Outcome, StkPushRequest


class _QuietHandler(BaseHTTPRequestHandler):
    inbox: queue.Queue

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode())
        self.inbox.put(payload)
        body = b'{"ResultCode":0,"ResultDesc":"Accepted"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def callback_inbox():
    inbox: queue.Queue = queue.Queue()

    class Handler(_QuietHandler):
        pass

    Handler.inbox = inbox
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/daraja/callback", inbox
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def provider():
    app.state.daraja.reset()
    client = httpx.Client(transport=httpx.ASGITransport(app=app), timeout=10.0)
    daraja = DarajaHttpProvider(
        base_url="http://xmoney.test/sandbox/daraja",
        consumer_key="sandbox",
        consumer_secret="sandbox",
        shortcode="174379",
        passkey="sandbox-passkey",
        client=client,
    )
    try:
        yield daraja
    finally:
        client.close()
        app.state.daraja.reset()


def _push(provider: DarajaHttpProvider, phone: str, url: str, *, key: str, cents: int = 10_000):
    return provider.stk_push(
        StkPushRequest(
            amount_cents=cents,
            phone_e164=phone,
            account_reference="amina",
            description="topup",
            callback_url=url,
            idempotency_key=key,
        )
    )


def test_stk_success_callback_is_delivered_and_parsed(provider, callback_inbox, engine) -> None:
    url, inbox = callback_inbox
    accepted = _push(provider, "+254700000000", url, key="stk-success-1")
    assert accepted.response_code == "0"
    assert accepted.checkout_request_id.startswith("ws_CO_")
    payload = inbox.get(timeout=3)
    parsed = provider.parse_stk_callback(payload)
    assert parsed.outcome is Outcome.SUCCESS
    assert parsed.result_code == 0
    assert parsed.checkout_request_id == accepted.checkout_request_id
    assert parsed.amount_cents == 10_000
    assert parsed.phone_e164 == "+254700000000"
    assert parsed.mpesa_receipt_number is not None
    assert parsed.mpesa_receipt_number.startswith("SBOX")
    body = app.state.daraja.last_stk_body
    assert body is not None
    assert body["Password"] == daraja_password("174379", "sandbox-passkey", body["Timestamp"])
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Posting)) == 0


@pytest.mark.parametrize(
    ("phone", "outcome", "code"),
    [
        ("+254700000032", Outcome.CANCELLED, 1032),
        ("+254700000037", Outcome.TIMEOUT, 1037),
        ("+254700000001", Outcome.INSUFFICIENT_FUNDS, 1),
    ],
)
def test_scripted_failure_callbacks(provider, callback_inbox, phone, outcome, code) -> None:
    url, inbox = callback_inbox
    _push(provider, phone, url, key=f"stk-{outcome.value}")
    parsed = parse_stk_callback(inbox.get(timeout=3))
    assert parsed.outcome is outcome
    assert parsed.result_code == code
    assert parsed.amount_cents is None
    assert parsed.mpesa_receipt_number is None


def test_suffix_drops_the_callback(provider, callback_inbox) -> None:
    url, inbox = callback_inbox
    _push(provider, "+254700000099", url, key="stk-drop-1")
    with pytest.raises(queue.Empty):
        inbox.get(timeout=0.4)
    attempts = app.state.daraja.attempts
    assert len(attempts) == 1
    assert attempts[0].dropped is True


def test_configured_delay_and_default_outcome(provider, callback_inbox) -> None:
    url, inbox = callback_inbox
    response = provider._client.put(
        provider._url("__control/behavior"),
        json={"outcome": "timeout", "delay_ms": 250, "drop_callback": False},
    )
    assert response.status_code == 200
    started = time.monotonic()
    _push(provider, "+254700000111", url, key="stk-delay-1")
    parsed = parse_stk_callback(inbox.get(timeout=3))
    assert time.monotonic() - started >= 0.2
    assert parsed.outcome is Outcome.TIMEOUT
    assert parsed.result_code == 1037


def test_stk_idempotency_does_not_send_a_second_callback(provider, callback_inbox) -> None:
    url, inbox = callback_inbox
    first = _push(provider, "+254700000000", url, key="stk-replay")
    inbox.get(timeout=3)
    second = _push(provider, "+254700000000", url, key="stk-replay")
    assert second.checkout_request_id == first.checkout_request_id
    with pytest.raises(queue.Empty):
        inbox.get(timeout=0.3)
    sent = [attempt for attempt in app.state.daraja.attempts if not attempt.dropped]
    assert len(sent) == 1


def test_stk_idempotency_conflict(provider, callback_inbox) -> None:
    url, inbox = callback_inbox
    _push(provider, "+254700000000", url, key="stk-conflict", cents=10_000)
    inbox.get(timeout=3)
    with pytest.raises(IdempotencyConflict):
        _push(provider, "+254700000000", url, key="stk-conflict", cents=20_000)


def test_oauth_and_stk_reject_missing_credentials(provider) -> None:
    missing = provider._client.get(provider._url("oauth/v1/generate"))
    assert missing.status_code == 400
    unauthenticated = provider._client.get(
        provider._url("oauth/v1/generate"),
        params={"grant_type": "client_credentials"},
    )
    assert unauthenticated.status_code == 401
    rejected = provider._client.post(
        provider._url("mpesa/stkpush/v1/processrequest"),
        json={"Amount": 1},
    )
    assert rejected.status_code == 401


def test_adapter_rejects_fractional_shillings_and_production(provider) -> None:
    with pytest.raises(InvalidAmount):
        _push(provider, "+254700000000", "http://127.0.0.1/cb", key="fraction", cents=150)
    with pytest.raises(SandboxViolation):
        DarajaHttpProvider(
            base_url="https://api.safaricom.co.ke",
            consumer_key="sandbox",
            consumer_secret="sandbox",
            shortcode="174379",
            passkey="sandbox-passkey",
        )
    allowed = DarajaHttpProvider(
        base_url="https://sandbox.safaricom.co.ke",
        consumer_key="sandbox",
        consumer_secret="sandbox",
        shortcode="174379",
        passkey="sandbox-passkey",
    )
    allowed.close()


def test_callback_parser_rejects_garbage_and_unknown_codes() -> None:
    with pytest.raises(CallbackParseError):
        parse_stk_callback({"hello": "world"})
    parsed = parse_stk_callback(
        {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "sandbox-1",
                    "CheckoutRequestID": "ws_CO_1",
                    "ResultCode": 1019,
                    "ResultDesc": "Transaction expired",
                }
            }
        }
    )
    assert parsed.outcome is None
    assert parsed.result_code == 1019
    cents = parse_stk_callback(
        {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "sandbox-1",
                    "CheckoutRequestID": "ws_CO_1",
                    "ResultCode": 0,
                    "ResultDesc": "ok",
                    "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": "10.5"}]},
                }
            }
        }
    )
    assert cents.amount_cents == 1_050
