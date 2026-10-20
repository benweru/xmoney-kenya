"""Recon runs are append-only. quieted_at is the one later stamp, from closed suspense."""

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
    Integer,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from xmoney.db import Base


class BreakKind(StrEnum):
    RUNNING_BALANCE_DRIFT = "running_balance_drift"
    TRIAL_UNBALANCED = "trial_unbalanced"
    AMOUNT_MISMATCH = "amount_mismatch"
    MISSING_ON_LEDGER = "missing_on_ledger"
    MISSING_ON_RAIL = "missing_on_rail"
    IN_FLIGHT_HOLD = "in_flight_hold"


class ReconRun(Base):
    __tablename__ = "recon_runs"
    __table_args__ = (
        CheckConstraint("break_count >= 0", name="ck_recon_runs_break_count"),
        CheckConstraint("unexplained_count >= 0", name="ck_recon_runs_unexplained"),
        Index("ix_recon_runs_started_at", "started_at"),
        {"comment": "One pass of the reconciler. Breaks for a run are classified, not repaired."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    break_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unexplained_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class ReconBreak(Base):
    __tablename__ = "recon_breaks"
    __table_args__ = (
        CheckConstraint(
            "kind IN ("
            "'running_balance_drift', 'trial_unbalanced', 'amount_mismatch', "
            "'missing_on_ledger', 'missing_on_rail', 'in_flight_hold')",
            name="ck_recon_breaks_kind",
        ),
        Index("ix_recon_breaks_run_id", "run_id"),
        Index(
            "ix_recon_breaks_quieted_subject",
            "subject_type",
            "subject_id",
            postgresql_where=text("quieted_at IS NOT NULL AND subject_id IS NOT NULL"),
        ),
        {"comment": "A classified difference found in one recon run. Suspense is a later slice."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("recon_runs.id", name="fk_recon_breaks_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    our_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    their_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[str] = mapped_column(String(500), nullable=False)
    quieted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
