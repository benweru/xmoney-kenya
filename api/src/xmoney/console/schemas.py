"""HTTP shapes for the staff console."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StaffSignInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str = Field(examples=["ops"])
    pin: str = Field(examples=["2580"])


class StaffMeOut(BaseModel):
    staff_user_id: UUID
    handle: str


class ConsoleUserOut(BaseModel):
    user_id: UUID
    handle: str
    phone: str
    wallet_account_id: UUID
    balance_cents: int
    created_at: datetime


class ConsoleHistoryItemOut(BaseModel):
    entry_id: UUID
    kind: str
    amount_cents: int
    counterparty: str | None
    note: str | None
    mpesa_receipt: str | None
    created_at: datetime


class ConsoleHistoryPageOut(BaseModel):
    items: list[ConsoleHistoryItemOut]
    next_cursor: str | None


class ConsoleJournalPostingOut(BaseModel):
    line_no: int
    account_id: UUID
    account_code: str
    direction: str
    amount_cents: int


class ConsoleJournalOut(BaseModel):
    id: UUID
    description: str
    external_ref: str | None
    created_at: datetime
    postings: list[ConsoleJournalPostingOut]


class ConsoleReconBreakOut(BaseModel):
    id: UUID
    kind: str
    subject_type: str
    subject_id: UUID | None
    our_cents: int | None
    their_cents: int | None
    detail: str


class ConsoleReconLatestOut(BaseModel):
    run_id: UUID | None
    started_at: datetime | None
    finished_at: datetime | None
    break_count: int
    unexplained_count: int
    breaks: list[ConsoleReconBreakOut]


class ConsoleSuspenseOut(BaseModel):
    id: UUID
    status: str
    amount_cents: int
    open_reason: str
    resolve_reason: str | None
    recon_break_id: UUID | None
    wallet_account_id: UUID | None
    created_at: datetime
    resolved_at: datetime | None


class ConsoleDlqJobOut(BaseModel):
    id: UUID
    kind: str
    attempts: int
    replays: int
    last_error: str | None
    updated_at: datetime
    payload: dict[str, Any]


class ConsoleAuditEventOut(BaseModel):
    id: UUID
    staff_handle: str
    action: str
    resource_type: str
    resource_id: str | None
    detail: str
    created_at: datetime
