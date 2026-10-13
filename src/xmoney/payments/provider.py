"""The seam Daraja sandbox and IntaSend will implement later.

Week 1's HTTP client speaks the classic Daraja STK surface. A future IntaSend
adapter implements the same protocol without the ledger knowing which rail it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Outcome(StrEnum):
    SUCCESS = "success"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    INSUFFICIENT_FUNDS = "insufficient_funds"


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_in: int


@dataclass(frozen=True)
class StkPushRequest:
    amount_cents: int
    phone_e164: str
    account_reference: str
    description: str
    callback_url: str
    idempotency_key: str


@dataclass(frozen=True)
class StkPushAccepted:
    merchant_request_id: str
    checkout_request_id: str
    response_code: str
    response_description: str
    customer_message: str


@dataclass(frozen=True)
class StkCallback:
    merchant_request_id: str
    checkout_request_id: str
    result_code: int
    result_desc: str
    outcome: Outcome | None
    amount_cents: int | None
    mpesa_receipt_number: str | None
    phone_e164: str | None


class PaymentsProvider(Protocol):
    name: str

    def obtain_token(self) -> AccessToken:
        """Fetch a short-lived rail token."""

    def stk_push(self, request: StkPushRequest) -> StkPushAccepted:
        """Ask the handset to authorize a whole-shilling collection."""

    def parse_stk_callback(self, payload: object) -> StkCallback:
        """Turn a rail callback body into a typed result. Does not post the ledger."""
