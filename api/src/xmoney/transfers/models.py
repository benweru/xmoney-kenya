"""Completed sends. A row exists only if its journal entry committed with it."""

from __future__ import annotations

from datetime import datetime
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

PRODUCT_P2P = "p2p"


class FeeSchedule(Base):
    __tablename__ = "fee_schedules"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_fee_schedules_version_positive"),
        CheckConstraint("free_count_per_calendar_month >= 0", name="ck_fee_schedules_free_count"),
        CheckConstraint("product IN ('p2p')", name="ck_fee_schedules_product"),
        UniqueConstraint("version", name="uq_fee_schedules_version"),
        UniqueConstraint("product", "version", name="uq_fee_schedules_product_version"),
        {
            "comment": "Append-only fee versions. A transfer stores the version it used.",
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    product: Mapped[str] = mapped_column(String(20), nullable=False)
    free_count_per_calendar_month: Mapped[int] = mapped_column(Integer, nullable=False)
    bands: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_transfers_amount_positive"),
        CheckConstraint("fee_cents >= 0", name="ck_transfers_fee_non_negative"),
        CheckConstraint(
            "(fee_schedule_id IS NULL) = (fee_schedule_version = 0)",
            name="ck_transfers_fee_schedule",
        ),
        CheckConstraint("sender_user_id <> recipient_user_id", name="ck_transfers_not_self"),
        CheckConstraint("char_length(request_hash) = 64", name="ck_transfers_hash_len"),
        UniqueConstraint(
            "sender_user_id", "idempotency_key", name="uq_transfers_sender_idempotency_key"
        ),
        UniqueConstraint("journal_entry_id", name="uq_transfers_journal_entry_id"),
        Index("ix_transfers_recipient_user_id", "recipient_user_id"),
        {"comment": "P2P sends. Immutable; each one points at the journal entry that moved it."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sender_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", name="fk_transfers_sender_user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    recipient_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", name="fk_transfers_recipient_user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    fee_schedule_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("fee_schedules.id", name="fk_transfers_fee_schedule_id", ondelete="RESTRICT"),
        nullable=True,
    )
    fee_schedule_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    note: Mapped[str | None] = mapped_column(String(140), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_entry_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("journal_entries.id", name="fk_transfers_journal_entry_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
