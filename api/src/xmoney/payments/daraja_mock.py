"""Headless Daraja stand-in for tests and local demos.

Pesa Playground is a Rust/Tauri desktop simulator. It is the wrong runtime for
pytest, so this process speaks the STK endpoints itself. Outcomes are chosen
by the last three digits of the MSISDN, or by PUT /__control/behavior for every
other number. STK Query reports "still processing" until the configured delay
has passed, then the same outcome the callback carried, even when the
callback was dropped. The public demo turns the control route off with
DARAJA_MOCK_CONTROL_ENABLED=false, so one visitor cannot change outcomes for
everyone; the suffix rules still apply.

| Suffix | Callback |
| --- | --- |
| 000 | success (ResultCode 0) |
| 032 | cancelled by user (1032) |
| 037 | timeout, handset unreachable (1037) |
| 001 | insufficient funds (1) |
| 099 | push is accepted, callback is never sent |
| other | the configured default, which starts as success |

Receipt numbers are prefixed with SBOX so they cannot be confused with a live
M-PESA receipt. This simulator does not post the ledger.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from xmoney.config import get_settings
from xmoney.payments.daraja import RESULT_CODES
from xmoney.payments.provider import Outcome

logger = logging.getLogger("xmoney.daraja_mock")

_PHONE_RE_MSISDN = re.compile(r"^254[17][0-9]{8}$")


@dataclass(frozen=True)
class Behavior:
    outcome: Outcome = Outcome.SUCCESS
    delay_ms: int = 0
    drop_callback: bool = False


# Suffix rules override the outcome (and, for 099, drop the callback).
# delay_ms is always taken from the configured default.
_SUFFIX_RULES: dict[str, tuple[Outcome, bool]] = {
    "000": (Outcome.SUCCESS, False),
    "032": (Outcome.CANCELLED, False),
    "037": (Outcome.TIMEOUT, False),
    "001": (Outcome.INSUFFICIENT_FUNDS, False),
    "099": (Outcome.SUCCESS, True),
}


@dataclass
class StkRecord:
    idempotency_key: str | None
    fingerprint: str
    merchant_request_id: str
    checkout_request_id: str
    phone: str
    amount_shillings: int
    callback_url: str
    outcome: Outcome = Outcome.SUCCESS
    completes_at: float = 0.0


@dataclass(frozen=True)
class CallbackAttempt:
    checkout_request_id: str
    dropped: bool
    payload: dict[str, object]


@dataclass
class DarajaMockState:
    default_behavior: Behavior = field(default_factory=Behavior)
    tokens: dict[str, float] = field(default_factory=dict)
    records_by_key: dict[str, StkRecord] = field(default_factory=dict)
    records_by_checkout: dict[str, StkRecord] = field(default_factory=dict)
    attempts: list[CallbackAttempt] = field(default_factory=list)
    last_stk_body: dict[str, object] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def reset(self) -> None:
        with self._lock:
            self.default_behavior = Behavior()
            self.tokens.clear()
            self.records_by_key.clear()
            self.records_by_checkout.clear()
            self.attempts.clear()
            self.last_stk_body = None

    def record_attempt(self, attempt: CallbackAttempt) -> None:
        with self._lock:
            self.attempts.append(attempt)


class BehaviorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Outcome = Outcome.SUCCESS
    delay_ms: int = Field(default=0, ge=0, le=10_000)
    drop_callback: bool = False


class StkPushBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    BusinessShortCode: str
    Password: str
    Timestamp: str
    TransactionType: str
    Amount: int | str
    PartyA: str
    PartyB: str
    PhoneNumber: str
    CallBackURL: str
    AccountReference: str
    TransactionDesc: str


class StkQueryBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    BusinessShortCode: str
    Password: str
    Timestamp: str
    CheckoutRequestID: str


def create_daraja_mock_app(state: DarajaMockState | None = None) -> FastAPI:
    mock_state = state or DarajaMockState()
    app = FastAPI(title="X Money Daraja mock", docs_url=None, redoc_url=None)
    app.state.daraja = mock_state
    app.include_router(build_daraja_router())
    return app


def build_daraja_router() -> APIRouter:
    router = APIRouter()

    @router.get("/__control/health")
    def control_health(request: Request) -> dict[str, object]:
        state = _state(request)
        behavior = state.default_behavior
        return {
            "simulator": "daraja",
            "mode": "sandbox",
            "moves_real_money": False,
            "outcome": behavior.outcome.value,
            "delay_ms": behavior.delay_ms,
            "drop_callback": behavior.drop_callback,
        }

    @router.put("/__control/behavior", response_model=None)
    def set_behavior(body: BehaviorIn, request: Request) -> dict[str, object] | JSONResponse:
        if not get_settings().daraja_mock_control_enabled:
            return _error(404, "404.000", "Not found")
        state = _state(request)
        with state._lock:
            state.default_behavior = Behavior(
                outcome=body.outcome,
                delay_ms=body.delay_ms,
                drop_callback=body.drop_callback,
            )
        return {
            "outcome": body.outcome.value,
            "delay_ms": body.delay_ms,
            "drop_callback": body.drop_callback,
        }

    @router.get("/oauth/v1/generate")
    def oauth(request: Request, grant_type: str = "") -> JSONResponse:
        if grant_type != "client_credentials":
            return _error(400, "400.001", "Invalid grant_type")
        decoded = _basic_credentials(request.headers.get("authorization", ""))
        if decoded is None:
            return _error(401, "401.001", "Invalid credentials")
        token = "sandbox." + secrets.token_urlsafe(24)
        state = _state(request)
        with state._lock:
            state.tokens[token] = time.monotonic() + 3599
        return JSONResponse(
            status_code=200,
            content={"access_token": token, "expires_in": "3599"},
        )

    @router.post("/mpesa/stkpush/v1/processrequest")
    def stk_push(
        body: StkPushBody,
        request: Request,
        background: BackgroundTasks,
    ) -> JSONResponse:
        state = _state(request)
        if not _bearer_is_valid(state, request.headers.get("authorization", "")):
            return _error(401, "404.001.03", "Invalid Access Token")
        problem = _validate_stk(body)
        if problem is not None:
            return problem
        amount = _whole_shillings(body.Amount)
        if amount is None:
            return _error(400, "400.002", "Amount must be a positive whole number of shillings")
        idempotency_key = request.headers.get("x-idempotency-key")
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip() or None
        fingerprint = _fingerprint(body, amount)
        with state._lock:
            state.last_stk_body = body.model_dump()
            behavior = _resolve_behavior(body.PhoneNumber, state.default_behavior)
            if idempotency_key is not None and idempotency_key in state.records_by_key:
                existing = state.records_by_key[idempotency_key]
                if existing.fingerprint != fingerprint:
                    return _error(
                        409,
                        "sandbox.idempotency_conflict",
                        "idempotency key was already used with a different STK request",
                    )
                return _accepted(existing)
            record = _new_record(body, amount, idempotency_key, fingerprint, behavior)
            if idempotency_key is not None:
                state.records_by_key[idempotency_key] = record
            state.records_by_checkout[record.checkout_request_id] = record

        payload = _callback_payload(record, behavior)
        if behavior.drop_callback:
            state.record_attempt(
                CallbackAttempt(
                    checkout_request_id=record.checkout_request_id,
                    dropped=True,
                    payload=payload,
                )
            )
        else:
            background.add_task(_deliver, state, record.callback_url, payload, behavior.delay_ms)
        return _accepted(record)

    @router.post("/mpesa/stkpushquery/v1/query")
    def stk_query(body: StkQueryBody, request: Request) -> JSONResponse:
        state = _state(request)
        if not _bearer_is_valid(state, request.headers.get("authorization", "")):
            return _error(401, "404.001.03", "Invalid Access Token")
        with state._lock:
            record = state.records_by_checkout.get(body.CheckoutRequestID)
        if record is None:
            return _error(400, "400.002.02", "Bad Request - Invalid CheckoutRequestID")
        if time.monotonic() < record.completes_at:
            return _error(500, "500.001.1001", "The transaction is being processed")
        code, desc = RESULT_CODES[record.outcome]
        return JSONResponse(
            status_code=200,
            content={
                "ResponseCode": "0",
                "ResponseDescription": "The service request has been accepted successfully",
                "MerchantRequestID": record.merchant_request_id,
                "CheckoutRequestID": record.checkout_request_id,
                "ResultCode": str(code),
                "ResultDesc": desc,
            },
        )

    return router


def _state(request: Request) -> DarajaMockState:
    state = request.app.state.daraja
    if not isinstance(state, DarajaMockState):
        raise RuntimeError("Daraja mock state is not configured")
    return state


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"errorCode": code, "errorMessage": message},
    )


def _basic_credentials(header: str) -> str | None:
    if not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1], validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    key, separator, secret = decoded.partition(":")
    if not separator or not key or not secret:
        return None
    return decoded


def _bearer_is_valid(state: DarajaMockState, header: str) -> bool:
    if not header.lower().startswith("bearer "):
        return False
    token = header.split(" ", 1)[1].strip()
    with state._lock:
        expires = state.tokens.get(token)
    return expires is not None and expires >= time.monotonic()


def _validate_stk(body: StkPushBody) -> JSONResponse | None:
    if body.TransactionType != "CustomerPayBillOnline":
        return _error(400, "400.002", "Unsupported TransactionType")
    if not body.BusinessShortCode or not body.PartyB:
        return _error(400, "400.002", "BusinessShortCode is required")
    if not body.Password or not body.Timestamp.isdigit() or len(body.Timestamp) != 14:
        return _error(400, "400.002", "Password and Timestamp are required")
    if _whole_shillings(body.Amount) is None:
        return _error(400, "400.002", "Amount must be a positive whole number of shillings")
    if _PHONE_RE_MSISDN.fullmatch(body.PhoneNumber) is None or body.PartyA != body.PhoneNumber:
        return _error(400, "400.002", "PhoneNumber must be a Kenyan MSISDN in 2547... form")
    parsed = urlparse(body.CallBackURL)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _error(400, "400.002", "CallBackURL must be http(s)")
    if not 1 <= len(body.AccountReference) <= 12:
        return _error(400, "400.002", "AccountReference must be 1-12 characters")
    if not 1 <= len(body.TransactionDesc) <= 13:
        return _error(400, "400.002", "TransactionDesc must be 1-13 characters")
    return None


def _whole_shillings(amount: int | str) -> int | None:
    if isinstance(amount, bool):
        return None
    if isinstance(amount, int) and amount > 0:
        return amount
    if isinstance(amount, str) and amount.isdigit() and int(amount) > 0:
        return int(amount)
    return None


def _fingerprint(body: StkPushBody, amount: int) -> str:
    payload = {
        "account_reference": body.AccountReference,
        "amount": amount,
        "callback_url": body.CallBackURL,
        "description": body.TransactionDesc,
        "phone": body.PhoneNumber,
        "shortcode": body.BusinessShortCode,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _resolve_behavior(phone: str, default: Behavior) -> Behavior:
    rule = _SUFFIX_RULES.get(phone[-3:])
    if rule is None:
        return default
    outcome, drop = rule
    return Behavior(outcome=outcome, delay_ms=default.delay_ms, drop_callback=drop)


def _new_record(
    body: StkPushBody,
    amount: int,
    idempotency_key: str | None,
    fingerprint: str,
    behavior: Behavior,
) -> StkRecord:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(4)
    return StkRecord(
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        merchant_request_id=f"sandbox-{stamp}-{suffix}",
        checkout_request_id=f"ws_CO_{stamp}{suffix}",
        phone=body.PhoneNumber,
        amount_shillings=amount,
        callback_url=body.CallBackURL,
        outcome=behavior.outcome,
        completes_at=time.monotonic() + behavior.delay_ms / 1000,
    )


def _accepted(record: StkRecord) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "MerchantRequestID": record.merchant_request_id,
            "CheckoutRequestID": record.checkout_request_id,
            "ResponseCode": "0",
            "ResponseDescription": "Success. Request accepted for processing",
            "CustomerMessage": "Success. Request accepted for processing",
        },
    )


def _callback_payload(record: StkRecord, behavior: Behavior) -> dict[str, object]:
    code, desc = RESULT_CODES[behavior.outcome]
    callback: dict[str, object] = {
        "MerchantRequestID": record.merchant_request_id,
        "CheckoutRequestID": record.checkout_request_id,
        "ResultCode": code,
        "ResultDesc": desc,
    }
    if behavior.outcome is Outcome.SUCCESS:
        callback["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": record.amount_shillings},
                {"Name": "MpesaReceiptNumber", "Value": _receipt()},
                {
                    "Name": "TransactionDate",
                    "Value": int(datetime.now(UTC).strftime("%Y%m%d%H%M%S")),
                },
                {"Name": "PhoneNumber", "Value": int(record.phone)},
            ]
        }
    return {"Body": {"stkCallback": callback}}


def _checkout_id(payload: Mapping[str, object]) -> str:
    body = payload.get("Body")
    if not isinstance(body, Mapping):
        return ""
    callback = body.get("stkCallback")
    if not isinstance(callback, Mapping):
        return ""
    return str(callback.get("CheckoutRequestID", ""))


def _receipt() -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "SBOX" + "".join(secrets.choice(alphabet) for _ in range(8))


def _deliver(state: DarajaMockState, url: str, payload: dict[str, object], delay_ms: int) -> None:
    try:
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)
        state.record_attempt(
            CallbackAttempt(
                checkout_request_id=_checkout_id(payload),
                dropped=False,
                payload=payload,
            )
        )
        httpx.post(url, json=payload, timeout=5.0)
    except Exception:
        logger.info("sandbox callback delivery failed", exc_info=True)
