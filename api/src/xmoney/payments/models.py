"""STK top-ups and every callback received for them."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from xmoney.db import Base


class TopupStatus(StrEnum):
    INITIATED = "initiated"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class CallbackDisposition(StrEnum):
    APPLIED = "applied"
    RECORDED = "recorded"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    AMOUNT_MISMATCH = "amount_mismatch"
    UNMATCHED = "unmatched"


class Topup(Base):
    __tablename__ = "topups"
    __table_args__ = (
        CheckConstraint(
            "amount_cents > 0 AND amount_cents % 100 = 0", name="ck_topups_whole_shillings"
        ),
        CheckConstraint(
            "status IN ('initiated', 'pending', 'succeeded', 'failed', 'expired')",
            name="ck_topups_status",
        ),
        CheckConstraint(
            "(status = 'succeeded') = (journal_entry_id IS NOT NULL)",
            name="ck_topups_succeeded_has_entry",
        ),
        CheckConstraint(
            "status = 'initiated' OR status = 'failed' OR status = 'expired' "
            "OR checkout_request_id IS NOT NULL",
            name="ck_topups_pending_has_checkout",
        ),
        CheckConstraint("char_length(request_hash) = 64", name="ck_topups_hash_len"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_topups_user_idempotency_key"),
        UniqueConstraint("checkout_request_id", name="uq_topups_checkout_request_id"),
        UniqueConstraint("mpesa_receipt_number", name="uq_topups_mpesa_receipt_number"),
        UniqueConstraint("journal_entry_id", name="uq_topups_journal_entry_id"),
        Index("ix_topups_status_created", "status", "created_at"),
        {"comment": "STK Push top-ups: initiated -> pending -> succeeded | failed | expired."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_topups_user_id", ondelete="RESTRICT"), nullable=False
    )
    wallet_account_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ledger_accounts.id", name="fk_topups_wallet_account_id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    phone_e164: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    merchant_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkout_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_desc: Mapped[str | None] = mapped_column(String(300), nullable=True)
    mpesa_receipt_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    journal_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("journal_entries.id", name="fk_topups_journal_entry_id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    queried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StkCallbackLog(Base):
    __tablename__ = "stk_callbacks"
    __table_args__ = (
        CheckConstraint(
            "disposition IN ("
            "'applied', 'duplicate', 'conflict', 'amount_mismatch', 'unmatched', 'recorded')",
            name="ck_stk_callbacks_disposition",
        ),
        Index("ix_stk_callbacks_checkout_request_id", "checkout_request_id"),
        {"comment": "Every STK callback as received, and what it did. Duplicates are kept."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    checkout_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    topup_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("topups.id", name="fk_stk_callbacks_topup_id", ondelete="RESTRICT"),
        nullable=True,
    )
    result_code: Mapped[int] = mapped_column(Integer, nullable=False)
    disposition: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
