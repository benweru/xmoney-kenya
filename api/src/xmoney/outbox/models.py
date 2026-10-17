"""The outbox: work to do outside the database, written in the same transaction as its cause."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from xmoney.db import Base


class JobStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    DEAD = "dead"


class OutboxJob(Base):
    __tablename__ = "outbox_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'done', 'dead')", name="ck_outbox_jobs_status"),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_outbox_jobs_attempts"),
        CheckConstraint(
            "(status = 'done') = (completed_at IS NOT NULL)", name="ck_outbox_jobs_done_has_time"
        ),
        CheckConstraint("status <> 'dead' OR lease_until IS NULL", name="ck_outbox_jobs_dead_free"),
        Index(
            "uq_outbox_jobs_kind_dedupe_key",
            "kind",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
        Index(
            "ix_outbox_jobs_due",
            "run_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_outbox_jobs_dead",
            "updated_at",
            postgresql_where=text("status = 'dead'"),
        ),
        {
            "comment": (
                "Work for the worker. Written in the same transaction as the business row "
                "that needs it: pending -> done | dead. Dead jobs are the DLQ."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=JobStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    replays: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # A claim is a lease. A worker killed mid-job lets it lapse and the job is retried.
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
