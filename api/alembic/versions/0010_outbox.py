"""Transactional outbox with retries and a dead-letter queue.

Revision ID: 0010_outbox
Revises: 0009_wallet_running_totals
Create Date: 2026-10-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_outbox"
down_revision: str | None = "0009_wallet_running_totals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("replays", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'done', 'dead')", name="ck_outbox_jobs_status"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_outbox_jobs_attempts"),
        sa.CheckConstraint(
            "(status = 'done') = (completed_at IS NOT NULL)", name="ck_outbox_jobs_done_has_time"
        ),
        sa.CheckConstraint(
            "status <> 'dead' OR lease_until IS NULL", name="ck_outbox_jobs_dead_free"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment=(
            "Work for the worker. Written in the same transaction as the business row "
            "that needs it: pending -> done | dead. Dead jobs are the DLQ."
        ),
    )
    op.create_index(
        "uq_outbox_jobs_kind_dedupe_key",
        "outbox_jobs",
        ["kind", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_index(
        "ix_outbox_jobs_due",
        "outbox_jobs",
        ["run_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_outbox_jobs_dead",
        "outbox_jobs",
        ["updated_at"],
        postgresql_where=sa.text("status = 'dead'"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_jobs_dead", table_name="outbox_jobs")
    op.drop_index("ix_outbox_jobs_due", table_name="outbox_jobs")
    op.drop_index("uq_outbox_jobs_kind_dedupe_key", table_name="outbox_jobs")
    op.drop_table("outbox_jobs")
