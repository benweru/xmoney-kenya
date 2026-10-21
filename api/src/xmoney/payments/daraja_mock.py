"""Headless Daraja stand-in for tests and local demos.

Pesa Playground is a Rust/Tauri desktop simulator. It is the wrong runtime for
pytest, so this process speaks the STK endpoints itself. Outcomes are chosen
by the last three digits of the MSISDN, or by PUT /__control/behavior for every
other number. STK Query reports "still processing" until the configured delay
has passed, then the same outcome the callback carried, even when the
callback was dropped. The default delay is 0 ms, so a query used to confirm
a callback is instant in tests and the local UI. The public demo turns the control route off with
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
M-PESA receipt. Successful STKs, including dropped callbacks, appear on
GET /mpesa/settlement/v1/file. PUT /__control/settlement injects an extra paid
row. POST /mpesa/transactionstatus/v1/query looks a receipt up and inlines
Result (sandbox only acknowledges). This simulator does not post the ledger.
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
class B2cRecord:
    idempotency_key: str | None
    fingerprint: str
    originator_conversation_id: str
    conversation_id: str
    phone: str
    amount_shillings: int
    result_url: str
    timeout_url: str
    outcome: Outcome = Outcome.SUCCESS
    completes_at: float = 0.0


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
    receipt: str | None = None
    drop_callback: bool = False


@dataclass(frozen=True)
class InjectedSettlement:
    receipt: str
    amount_shillings: int
    phone: str
    checkout_request_id: str | None = None


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
    b2c_by_key: dict[str, B2cRecord] = field(default_factory=dict)
    b2c_by_originator: dict[str, B2cRecord] = field(default_factory=dict)
    attempts: list[CallbackAttempt] = field(default_factory=list)
    injected_settlement: list[InjectedSettlement] = field(default_factory=list)
    last_stk_body: dict[str, object] | None = None
    last_b2c_body: dict[str, object] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def reset(self) -> None:
        with self._lock:
            self.default_behavior = Behavior()
            self.tokens.clear()
            self.records_by_key.clear()
            self.records_by_checkout.clear()
            self.b2c_by_key.clear()
            self.b2c_by_originator.clear()
            self.attempts.clear()
            self.injected_settlement.clear()
            self.last_stk_body = None
            self.last_b2c_body = None

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


class B2cPaymentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    OriginatorConversationID: str
    InitiatorName: str
    SecurityCredential: str
    CommandID: str
    Amount: int | str
    PartyA: str
    PartyB: str
    Remarks: str
    QueueTimeOutURL: str
    ResultURL: str
    Occasion: str


class StkQueryBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    BusinessShortCode: str
    Password: str
    Timestamp: str
    CheckoutRequestID: str


class SettlementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    TransactionID: str = Field(min_length=1, max_length=40)
    Amount: int = Field(gt=0, le=250_000)
    PhoneNumber: str
    CheckoutRequestID: str | None = Field(default=None, max_length=64)


class TransactionStatusBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    Initiator: str
    SecurityCredential: str
    CommandID: str
    TransactionID: str
    PartyA: str
    IdentifierType: str
    ResultURL: str
    QueueTimeOutURL: str
    Remarks: str = ""
    Occasion: str = ""


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

    @router.get("/mpesa/settlement/v1/file")
    def settlement_file(request: Request) -> JSONResponse:
        state = _state(request)
        if not _bearer_is_valid(state, request.headers.get("authorization", "")):
            return _error(401, "404.001.03", "Invalid Access Token")
        now = time.monotonic()
        with state._lock:
            rows = [
                _settlement_item(record)
                for record in state.records_by_checkout.values()
                if record.outcome is Outcome.SUCCESS
                and record.receipt is not None
                and now >= record.completes_at
            ]
            rows.extend(_injected_item(row) for row in state.injected_settlement)
        return JSONResponse(status_code=200, content={"transactions": rows})

    @router.put("/__control/settlement", response_model=None)
    def inject_settlement(body: SettlementIn, request: Request) -> dict[str, object] | JSONResponse:
        if not get_settings().daraja_mock_control_enabled:
            return _error(404, "404.000", "Not found")
        if _PHONE_RE_MSISDN.fullmatch(body.PhoneNumber) is None:
            return _error(400, "400.002", "PhoneNumber must be a Kenyan MSISDN in 2547... form")
        injected = InjectedSettlement(
            receipt=body.TransactionID.strip(),
            amount_shillings=body.Amount,
            phone=body.PhoneNumber,
            checkout_request_id=(
                body.CheckoutRequestID.strip() if body.CheckoutRequestID else None
            ),
        )
        if not injected.receipt:
            return _error(400, "400.002", "TransactionID is required")
        state = _state(request)
        with state._lock:
            if any(row.receipt == injected.receipt for row in state.injected_settlement):
                return _error(409, "sandbox.idempotency_conflict", "TransactionID already injected")
            for record in state.records_by_checkout.values():
                if record.receipt == injected.receipt:
                    return _error(
                        409,
                        "sandbox.idempotency_conflict",
                        "TransactionID already exists on an STK",
                    )
            state.injected_settlement.append(injected)
        return {
            "TransactionID": injected.receipt,
            "Amount": injected.amount_shillings,
            "PhoneNumber": injected.phone,
            "CheckoutRequestID": injected.checkout_request_id,
        }

    @router.post("/mpesa/transactionstatus/v1/query")
    def transaction_status(body: TransactionStatusBody, request: Request) -> JSONResponse:
        state = _state(request)
        if not _bearer_is_valid(state, request.headers.get("authorization", "")):
            return _error(401, "404.001.03", "Invalid Access Token")
        problem = _validate_transaction_status(body)
        if problem is not None:
            return problem
        record, injected = _lookup_paid(state, body.TransactionID)
        if record is None and injected is None:
            return _error(400, "400.002.02", "Bad Request - Invalid TransactionID")
        if record is not None and time.monotonic() < record.completes_at:
            return _error(500, "500.001.1001", "The transaction is being processed")
        return JSONResponse(status_code=200, content=_transaction_status_body(record, injected))

    @router.post("/mpesa/b2c/v1/paymentrequest")
    def b2c_payment(
        body: B2cPaymentBody,
        request: Request,
        background: BackgroundTasks,
    ) -> JSONResponse:
        state = _state(request)
        if not _bearer_is_valid(state, request.headers.get("authorization", "")):
            return _error(401, "404.001.03", "Invalid Access Token")
        problem = _validate_b2c(body)
        if problem is not None:
            return problem
        amount = _whole_shillings(body.Amount)
        if amount is None:
            return _error(400, "400.002", "Amount must be a positive whole number of shillings")
        idempotency_key = request.headers.get("x-idempotency-key")
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip() or None
        fingerprint = _b2c_fingerprint(body, amount)
        with state._lock:
            state.last_b2c_body = body.model_dump()
            behavior = _resolve_behavior(body.PartyB, state.default_behavior)
            if idempotency_key is not None and idempotency_key in state.b2c_by_key:
                existing = state.b2c_by_key[idempotency_key]
                if existing.fingerprint != fingerprint:
                    return _error(
                        409,
                        "sandbox.idempotency_conflict",
                        "idempotency key was already used with a different B2C request",
                    )
                return _b2c_accepted(existing)
            record = _new_b2c_record(body, amount, idempotency_key, fingerprint, behavior)
            if idempotency_key is not None:
                state.b2c_by_key[idempotency_key] = record
            state.b2c_by_originator[record.originator_conversation_id] = record

        payload = _b2c_callback_payload(record, behavior)
        target = record.timeout_url if behavior.outcome is Outcome.TIMEOUT else record.result_url
        if behavior.drop_callback:
            state.record_attempt(
                CallbackAttempt(
                    checkout_request_id=record.conversation_id,
                    dropped=True,
                    payload=payload,
                )
            )
        else:
            background.add_task(_deliver, state, target, payload, behavior.delay_ms)
        return _b2c_accepted(record)

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


def _validate_b2c(body: B2cPaymentBody) -> JSONResponse | None:
    if body.CommandID != "BusinessPayment":
        return _error(400, "400.002", "Unsupported CommandID")
    if not body.InitiatorName or not body.SecurityCredential or not body.PartyA:
        return _error(400, "400.002", "InitiatorName, SecurityCredential and PartyA are required")
    if not body.OriginatorConversationID or len(body.OriginatorConversationID) > 64:
        return _error(400, "400.002", "OriginatorConversationID is required")
    if _whole_shillings(body.Amount) is None:
        return _error(400, "400.002", "Amount must be a positive whole number of shillings")
    if _PHONE_RE_MSISDN.fullmatch(body.PartyB) is None:
        return _error(400, "400.002", "PartyB must be a Kenyan MSISDN in 2547... form")
    for url in (body.ResultURL, body.QueueTimeOutURL):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return _error(400, "400.002", "ResultURL and QueueTimeOutURL must be http(s)")
    if not 1 <= len(body.Remarks) <= 100:
        return _error(400, "400.002", "Remarks must be 1-100 characters")
    if not 1 <= len(body.Occasion) <= 100:
        return _error(400, "400.002", "Occasion must be 1-100 characters")
    return None


def _validate_transaction_status(body: TransactionStatusBody) -> JSONResponse | None:
    if body.CommandID != "TransactionStatusQuery":
        return _error(400, "400.002", "Unsupported CommandID")
    if not body.Initiator or not body.SecurityCredential or not body.PartyA:
        return _error(400, "400.002", "Initiator, SecurityCredential and PartyA are required")
    if not body.TransactionID.strip():
        return _error(400, "400.002", "TransactionID is required")
    if body.IdentifierType != "4":
        return _error(400, "400.002", "IdentifierType 4 (shortcode) is required")
    for url in (body.ResultURL, body.QueueTimeOutURL):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return _error(400, "400.002", "ResultURL and QueueTimeOutURL must be http(s)")
    return None


def _lookup_paid(
    state: DarajaMockState, transaction_id: str
) -> tuple[StkRecord | None, InjectedSettlement | None]:
    txn = transaction_id.strip()
    with state._lock:
        for record in state.records_by_checkout.values():
            if record.receipt == txn:
                return record, None
        for injected in state.injected_settlement:
            if injected.receipt == txn:
                return None, injected
    return None, None


def _settlement_item(record: StkRecord) -> dict[str, object]:
    return {
        "TransactionID": record.receipt,
        "CheckoutRequestID": record.checkout_request_id,
        "Amount": record.amount_shillings,
        "PhoneNumber": record.phone,
        "ResultCode": 0,
        "CallbackDelivered": not record.drop_callback,
    }


def _injected_item(row: InjectedSettlement) -> dict[str, object]:
    item: dict[str, object] = {
        "TransactionID": row.receipt,
        "Amount": row.amount_shillings,
        "PhoneNumber": row.phone,
        "ResultCode": 0,
        "CallbackDelivered": False,
    }
    if row.checkout_request_id:
        item["CheckoutRequestID"] = row.checkout_request_id
    return item


def _transaction_status_body(
    record: StkRecord | None, injected: InjectedSettlement | None
) -> dict[str, object]:
    checkout: str | None
    receipt: str
    amount: int | None
    if record is not None:
        code, desc = RESULT_CODES[record.outcome]
        paid = record.outcome is Outcome.SUCCESS
        amount = record.amount_shillings if paid else None
        receipt = record.receipt if paid and record.receipt is not None else ""
        checkout = record.checkout_request_id
        conversation = record.merchant_request_id
    else:
        assert injected is not None
        code, desc = RESULT_CODES[Outcome.SUCCESS]
        paid = True
        amount = injected.amount_shillings
        receipt = injected.receipt
        checkout = injected.checkout_request_id
        conversation = f"inject-{injected.receipt}"
    parameters: list[dict[str, object]] = [
        {"Key": "TransactionStatus", "Value": "Completed" if paid else "Failed"},
        {"Key": "ReceiptNo", "Value": receipt},
    ]
    if amount is not None:
        parameters.append({"Key": "Amount", "Value": amount})
    if checkout:
        parameters.append({"Key": "CheckoutRequestID", "Value": checkout})
    return {
        "OriginatorConversationID": conversation,
        "ConversationID": conversation,
        "ResponseCode": "0",
        "ResponseDescription": "Accept the service request successfully.",
        "Result": {
            "ResultType": 0,
            "ResultCode": code,
            "ResultDesc": desc,
            "OriginatorConversationID": conversation,
            "ConversationID": conversation,
            "TransactionID": receipt,
            "ResultParameters": {"ResultParameter": parameters},
        },
    }


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


def _b2c_fingerprint(body: B2cPaymentBody, amount: int) -> str:
    payload = {
        "amount": amount,
        "occasion": body.Occasion,
        "originator": body.OriginatorConversationID,
        "phone": body.PartyB,
        "remarks": body.Remarks,
        "result_url": body.ResultURL,
        "shortcode": body.PartyA,
        "timeout_url": body.QueueTimeOutURL,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


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


def _new_b2c_record(
    body: B2cPaymentBody,
    amount: int,
    idempotency_key: str | None,
    fingerprint: str,
    behavior: Behavior,
) -> B2cRecord:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(4)
    return B2cRecord(
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        originator_conversation_id=body.OriginatorConversationID,
        conversation_id=f"AG_{stamp}_{suffix}",
        phone=body.PartyB,
        amount_shillings=amount,
        result_url=body.ResultURL,
        timeout_url=body.QueueTimeOutURL,
        outcome=behavior.outcome,
        completes_at=time.monotonic() + behavior.delay_ms / 1000,
    )


def _b2c_accepted(record: B2cRecord) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "ConversationID": record.conversation_id,
            "OriginatorConversationID": record.originator_conversation_id,
            "ResponseCode": "0",
            "ResponseDescription": "Accept the service request successfully.",
        },
    )


def _b2c_callback_payload(record: B2cRecord, behavior: Behavior) -> dict[str, object]:
    code, desc = RESULT_CODES[behavior.outcome]
    timed_out = behavior.outcome is Outcome.TIMEOUT
    result: dict[str, object] = {
        "ResultType": 1 if timed_out else 0,
        "ResultCode": code,
        "ResultDesc": desc if not timed_out else "The service request timed out.",
        "OriginatorConversationID": record.originator_conversation_id,
        "ConversationID": record.conversation_id,
        "TransactionID": _receipt() if behavior.outcome is Outcome.SUCCESS else "",
    }
    if behavior.outcome is Outcome.SUCCESS:
        result["ResultParameters"] = {
            "ResultParameter": [
                {"Key": "TransactionAmount", "Value": record.amount_shillings},
                {"Key": "TransactionReceipt", "Value": result["TransactionID"]},
                {"Key": "ReceiverPartyPublicName", "Value": f"{record.phone} - Customer"},
            ]
        }
    return {"Result": result}


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
        receipt=_receipt() if behavior.outcome is Outcome.SUCCESS else None,
        drop_callback=behavior.drop_callback,
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
        assert record.receipt is not None
        callback["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": record.amount_shillings},
                {"Name": "MpesaReceiptNumber", "Value": record.receipt},
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
