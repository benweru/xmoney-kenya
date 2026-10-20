"""Suspense items. Opening and resolving each post a journal entry."""

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


class SuspenseStatus(StrEnum):
    OPEN = "open"
    APPLIED = "applied"
    REFUNDED = "refunded"


class SuspenseItem(Base):
    __tablename__ = "suspense_items"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_suspense_amount_positive"),
        CheckConstraint(
            "status IN ('open', 'applied', 'refunded')",
            name="ck_suspense_status",
        ),
        CheckConstraint(
            "(status = 'open') = (resolve_journal_entry_id IS NULL)",
            name="ck_suspense_open_unresolved",
        ),
        CheckConstraint(
            "(status = 'applied') = (wallet_account_id IS NOT NULL)",
            name="ck_suspense_applied_has_wallet",
        ),
        CheckConstraint(
            "status = 'open' OR resolve_reason IS NOT NULL",
            name="ck_suspense_resolved_has_reason",
        ),
        UniqueConstraint("open_journal_entry_id", name="uq_suspense_open_journal"),
        UniqueConstraint("resolve_journal_entry_id", name="uq_suspense_resolve_journal"),
        Index("ix_suspense_status", "status"),
        Index(
            "uq_suspense_open_break",
            "recon_break_id",
            unique=True,
            postgresql_where=text("recon_break_id IS NOT NULL AND status = 'open'"),
        ),
        {"comment": "Unmatched value parked in system:suspense, then applied or refunded."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    recon_break_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("recon_breaks.id", name="fk_suspense_recon_break_id", ondelete="RESTRICT"),
        nullable=True,
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    open_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    resolve_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    open_journal_entry_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "journal_entries.id", name="fk_suspense_open_journal_entry_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    resolve_journal_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "journal_entries.id",
            name="fk_suspense_resolve_journal_entry_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    wallet_account_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("ledger_accounts.id", name="fk_suspense_wallet_account_id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
