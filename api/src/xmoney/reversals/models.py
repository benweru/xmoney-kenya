"""Reversal requests. The original journal entry is never edited."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from xmoney.db import Base


class ReversalStatus(StrEnum):
    PROPOSED = "proposed"
    POSTED = "posted"
    REJECTED = "rejected"


class Reversal(Base):
    __tablename__ = "reversals"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_reversals_amount_positive"),
        CheckConstraint(
            "status IN ('proposed', 'posted', 'rejected')",
            name="ck_reversals_status",
        ),
        CheckConstraint(
            "(status = 'posted') = (reversal_journal_entry_id IS NOT NULL)",
            name="ck_reversals_posted_has_entry",
        ),
        CheckConstraint(
            "status <> 'rejected' OR checker IS NOT NULL",
            name="ck_reversals_rejected_has_checker",
        ),
        UniqueConstraint(
            "reversal_journal_entry_id", name="uq_reversals_reversal_journal_entry_id"
        ),
        Index("ix_reversals_status", "status"),
        Index(
            "uq_reversals_original_active",
            "original_journal_entry_id",
            unique=True,
            postgresql_where=text("status IN ('proposed', 'posted')"),
        ),
        {"comment": "Compensating entries. Large amounts need a second actor before posting."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    original_journal_entry_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "journal_entries.id",
            name="fk_reversals_original_journal_entry_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    maker: Mapped[str] = mapped_column(String(40), nullable=False)
    checker: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reversal_journal_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "journal_entries.id",
            name="fk_reversals_reversal_journal_entry_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
