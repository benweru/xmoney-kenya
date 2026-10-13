"""HTTP shapes for top-ups."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from xmoney.payments.topups import TopupView


class TopupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Strict so JSON 100.0 and "100" are rejected instead of coerced to cents.
    amount_cents: StrictInt = Field(examples=[50_000])
    phone: str | None = Field(
        default=None,
        examples=["+254708374149"],
        description="The M-PESA line to prompt. Defaults to the signed-in user's phone.",
    )
    rail: Literal["mock", "sandbox"] | None = Field(
        default=None,
        description="The rail for the STK Push. Defaults to GET /v1/payment-rails `default`.",
    )


class RailOut(BaseModel):
    name: str
    label: str
    restricted: bool = Field(description="Only the demo owner's test phones can use it.")


class RailsOut(BaseModel):
    default: str
    rails: list[RailOut]


class TopupOut(BaseModel):
    id: UUID
    status: str
    rail: str
    amount_cents: int
    phone: str
    checkout_request_id: str | None
    mpesa_receipt_number: str | None
    result_code: int | None
    result_desc: str | None
    created_at: datetime
    resolved_at: datetime | None
    idempotent_replay: bool

    @classmethod
    def of(cls, view: TopupView) -> TopupOut:
        return cls(
            id=view.id,
            status=view.status.value,
            rail=view.rail,
            amount_cents=view.amount_cents,
            phone=view.phone_e164,
            checkout_request_id=view.checkout_request_id,
            mpesa_receipt_number=view.mpesa_receipt_number,
            result_code=view.result_code,
            result_desc=view.result_desc,
            created_at=view.created_at,
            resolved_at=view.resolved_at,
            idempotent_replay=view.idempotent_replay,
        )
