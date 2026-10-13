"""HTTP shapes for balances and sandbox journal posts."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from xmoney.ledger.money import Direction, PostCommand, PostingLine


class PostingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    direction: Direction
    # Strict so JSON 100.0 and "100" are rejected instead of coerced to cents.
    amount_cents: StrictInt


class PostEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(examples=["demo-topup-1"])
    description: str = Field(examples=["Sandbox float to wallet"])
    external_ref: str | None = None
    postings: list[PostingIn]

    def to_command(self) -> PostCommand:
        return PostCommand(
            idempotency_key=self.idempotency_key,
            description=self.description,
            external_ref=self.external_ref,
            postings=tuple(
                PostingLine(
                    account_id=line.account_id,
                    direction=line.direction,
                    amount_cents=line.amount_cents,
                )
                for line in self.postings
            ),
        )


class PostingOut(BaseModel):
    line_no: int
    account_id: UUID
    direction: str
    amount_cents: int


class JournalEntryOut(BaseModel):
    id: UUID
    idempotency_key: str
    description: str
    external_ref: str | None
    idempotent_replay: bool
    postings: list[PostingOut]


class BalanceOut(BaseModel):
    account_id: UUID
    code: str
    currency: str
    normal_side: str
    debit_cents: int
    credit_cents: int
    balance_cents: int
