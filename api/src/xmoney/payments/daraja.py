"""Daraja STK client. Production api.safaricom.co.ke is refused."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx

from xmoney.errors import (
    CallbackParseError,
    IdempotencyConflict,
    InvalidAmount,
    InvalidPaymentRequest,
    ProviderError,
)
from xmoney.identity.validators import normalize_phone
from xmoney.ledger.money import require_idempotency_key
from xmoney.payments.provider import (
    AccessToken,
    Outcome,
    StkCallback,
    StkPushAccepted,
    StkPushRequest,
    StkQueryResult,
)
from xmoney.sandbox import assert_sandbox_daraja_host

RESULT_CODES: dict[Outcome, tuple[int, str]] = {
    Outcome.SUCCESS: (0, "The service request is processed successfully."),
    Outcome.CANCELLED: (1032, "Request cancelled by user"),
    Outcome.TIMEOUT: (1037, "DS timeout user cannot be reached"),
    Outcome.INSUFFICIENT_FUNDS: (1, "The balance is insufficient for the transaction."),
}
_OUTCOME_BY_CODE = {code: outcome for outcome, (code, _desc) in RESULT_CODES.items()}

# STK Query answers HTTP 500 with this code while the customer has not responded.
_STILL_PROCESSING = "500.001.1001"

# Daraja documents a per-transaction cap. The sandbox mock enforces the same bound.
_MAX_STK_SHILLINGS = 250_000


def daraja_password(shortcode: str, passkey: str, timestamp: str) -> str:
    raw = f"{shortcode}{passkey}{timestamp}".encode()
    return base64.b64encode(raw).decode("ascii")


def parse_stk_callback(payload: object) -> StkCallback:
    if not isinstance(payload, Mapping):
        raise CallbackParseError("STK callback must be a JSON object")
    try:
        callback = payload["Body"]["stkCallback"]
        result_code = int(callback["ResultCode"])
        result_desc = str(callback["ResultDesc"])
        merchant = str(callback["MerchantRequestID"])
        checkout = str(callback["CheckoutRequestID"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CallbackParseError("STK callback is missing Body.stkCallback fields") from exc

    amount_cents: int | None = None
    receipt: str | None = None
    phone: str | None = None
    metadata = callback.get("CallbackMetadata") if isinstance(callback, Mapping) else None
    if isinstance(metadata, Mapping):
        values = _metadata_values(metadata.get("Item"))
        if values.get("Amount") is not None:
            amount_cents = _shillings_to_cents(values["Amount"])
        if values.get("MpesaReceiptNumber") is not None:
            receipt = str(values["MpesaReceiptNumber"])
        if values.get("PhoneNumber") is not None:
            phone = _phone_from_daraja(values["PhoneNumber"])
    return StkCallback(
        merchant_request_id=merchant,
        checkout_request_id=checkout,
        result_code=result_code,
        result_desc=result_desc,
        outcome=_OUTCOME_BY_CODE.get(result_code),
        amount_cents=amount_cents,
        mpesa_receipt_number=receipt,
        phone_e164=phone,
    )


class DarajaHttpProvider:
    """HTTP adapter for the local mock and the Daraja sandbox."""

    name = "daraja"

    def __init__(
        self,
        *,
        base_url: str,
        consumer_key: str,
        consumer_secret: str,
        shortcode: str,
        passkey: str,
        name: str = "daraja",
        client: httpx.Client | None = None,
    ) -> None:
        assert_sandbox_daraja_host(base_url)
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.shortcode = shortcode
        self.passkey = passkey
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=self.base_url, timeout=10.0)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def obtain_token(self) -> AccessToken:
        basic = base64.b64encode(f"{self.consumer_key}:{self.consumer_secret}".encode()).decode()
        response = self._client.get(
            self._url("oauth/v1/generate"),
            params={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}"},
        )
        body = _json_or_empty(response)
        if response.status_code != 200:
            raise ProviderError(
                _error_message(body, "OAuth failed"),
                status_code=response.status_code,
            )
        try:
            return AccessToken(token=str(body["access_token"]), expires_in=int(body["expires_in"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("OAuth response was missing access_token") from exc

    def stk_push(self, request: StkPushRequest) -> StkPushAccepted:
        shillings = _whole_shillings(request.amount_cents)
        phone = normalize_phone(request.phone_e164)
        msisdn = phone.removeprefix("+")
        _require_reference(request.account_reference)
        _require_description(request.description)
        _require_http_url(request.callback_url)
        idempotency_key = require_idempotency_key(request.idempotency_key)
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        token = self.obtain_token()
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": daraja_password(self.shortcode, self.passkey, timestamp),
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": shillings,
            "PartyA": msisdn,
            "PartyB": self.shortcode,
            "PhoneNumber": msisdn,
            "CallBackURL": request.callback_url,
            "AccountReference": request.account_reference,
            "TransactionDesc": request.description,
        }
        response = self._client.post(
            self._url("mpesa/stkpush/v1/processrequest"),
            json=payload,
            headers={
                "Authorization": f"Bearer {token.token}",
                "X-Idempotency-Key": idempotency_key,
            },
        )
        body = _json_or_empty(response)
        if response.status_code == 409:
            raise IdempotencyConflict(_error_message(body, "idempotency key was reused"))
        if response.status_code != 200:
            raise ProviderError(
                _error_message(body, "STK push was rejected"),
                status_code=response.status_code,
            )
        try:
            accepted = StkPushAccepted(
                merchant_request_id=str(body["MerchantRequestID"]),
                checkout_request_id=str(body["CheckoutRequestID"]),
                response_code=str(body["ResponseCode"]),
                response_description=str(body["ResponseDescription"]),
                customer_message=str(body["CustomerMessage"]),
            )
        except KeyError as exc:
            raise ProviderError("STK response was missing CheckoutRequestID") from exc
        if accepted.response_code != "0":
            raise ProviderError(
                f"STK push was not accepted (ResponseCode {accepted.response_code}): "
                f"{accepted.response_description}"
            )
        return accepted

    def stk_query(self, checkout_request_id: str) -> StkQueryResult:
        if not isinstance(checkout_request_id, str) or not checkout_request_id.strip():
            raise InvalidPaymentRequest("checkout_request_id is required")
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        token = self.obtain_token()
        response = self._client.post(
            self._url("mpesa/stkpushquery/v1/query"),
            json={
                "BusinessShortCode": self.shortcode,
                "Password": daraja_password(self.shortcode, self.passkey, timestamp),
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_request_id,
            },
            headers={"Authorization": f"Bearer {token.token}"},
        )
        body = _json_or_empty(response)
        if str(body.get("errorCode", "")) == _STILL_PROCESSING:
            return StkQueryResult(
                checkout_request_id=checkout_request_id,
                processing=True,
                result_code=None,
                result_desc=_error_message(body, "The transaction is being processed"),
                outcome=None,
            )
        if response.status_code != 200:
            raise ProviderError(
                _error_message(body, "STK query was rejected"),
                status_code=response.status_code,
            )
        try:
            result_code = int(body["ResultCode"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("STK query response was missing ResultCode") from exc
        return StkQueryResult(
            checkout_request_id=checkout_request_id,
            processing=False,
            result_code=result_code,
            result_desc=str(body.get("ResultDesc", "")),
            outcome=_OUTCOME_BY_CODE.get(result_code),
        )

    def parse_stk_callback(self, payload: object) -> StkCallback:
        return parse_stk_callback(payload)

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


def _whole_shillings(amount_cents: int) -> int:
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise InvalidAmount("STK amount_cents must be an integer")
    if amount_cents <= 0 or amount_cents % 100 != 0:
        raise InvalidAmount("M-PESA STK Push requires a positive whole number of shillings")
    shillings = amount_cents // 100
    if shillings > _MAX_STK_SHILLINGS:
        raise InvalidAmount(f"STK amount cannot exceed {_MAX_STK_SHILLINGS} KES")
    return shillings


def _require_reference(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 12:
        raise InvalidPaymentRequest("account_reference must be 1-12 characters")


def _require_description(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 13:
        raise InvalidPaymentRequest("description must be 1-13 characters")


def _require_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidPaymentRequest("callback_url must be an http(s) URL")


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error_message(body: Mapping[str, Any], fallback: str) -> str:
    message = body.get("errorMessage") or body.get("message")
    return str(message) if message else fallback


def _metadata_values(items: object) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if not isinstance(items, list):
        return values
    for item in items:
        if isinstance(item, Mapping) and "Name" in item:
            values[str(item["Name"])] = item.get("Value")
    return values


def _shillings_to_cents(value: object) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CallbackParseError("callback amount is not numeric") from exc
    if not amount.is_finite() or amount <= 0:
        raise CallbackParseError("callback amount must be a positive number")
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _phone_from_daraja(value: object) -> str:
    digits = str(value)
    if digits.startswith("+"):
        candidate = digits
    else:
        candidate = f"+{digits}"
    return normalize_phone(candidate)
