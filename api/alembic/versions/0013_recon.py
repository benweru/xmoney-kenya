"""Reconciliation runs and classified breaks.

Revision ID: 0013_recon
Revises: 0012_fee_schedules
Create Date: 2026-10-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_recon"
down_revision: str | None = "0012_fee_schedules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = (
    "running_balance_drift",
    "trial_unbalanced",
    "amount_mismatch",
    "missing_on_ledger",
    "missing_on_rail",
    "in_flight_hold",
)


def upgrade() -> None:
    op.create_table(
        "recon_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("break_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unexplained_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("break_count >= 0", name="ck_recon_runs_break_count"),
        sa.CheckConstraint("unexplained_count >= 0", name="ck_recon_runs_unexplained"),
        comment="One pass of the reconciler. Breaks for a run are classified, not repaired.",
    )
    op.create_table(
        "recon_breaks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("our_cents", sa.BigInteger(), nullable=True),
        sa.Column("their_cents", sa.BigInteger(), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["recon_runs.id"], name="fk_recon_breaks_run_id", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in _KINDS) + ")",
            name="ck_recon_breaks_kind",
        ),
        comment="A classified difference found in one recon run. Suspense is a later slice.",
    )
    op.create_index("ix_recon_breaks_run_id", "recon_breaks", ["run_id"])
    op.create_index("ix_recon_runs_started_at", "recon_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_recon_runs_started_at", table_name="recon_runs")
    op.drop_index("ix_recon_breaks_run_id", table_name="recon_breaks")
    op.drop_table("recon_breaks")
    op.drop_table("recon_runs")
