"""Reversals: compensating entries, with maker-checker for large amounts.

Revision ID: 0015_reversals
Revises: 0014_suspense
Create Date: 2026-10-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_reversals"
down_revision: str | None = "0014_suspense"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reversals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("original_journal_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("maker", sa.String(length=40), nullable=False),
        sa.Column("checker", sa.String(length=40), nullable=True),
        sa.Column("decision_reason", sa.String(length=500), nullable=True),
        sa.Column("reversal_journal_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_cents > 0", name="ck_reversals_amount_positive"),
        sa.CheckConstraint(
            "status IN ('proposed', 'posted', 'rejected')",
            name="ck_reversals_status",
        ),
        sa.CheckConstraint(
            "(status = 'posted') = (reversal_journal_entry_id IS NOT NULL)",
            name="ck_reversals_posted_has_entry",
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR checker IS NOT NULL",
            name="ck_reversals_rejected_has_checker",
        ),
        sa.ForeignKeyConstraint(
            ["original_journal_entry_id"],
            ["journal_entries.id"],
            name="fk_reversals_original_journal_entry_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reversal_journal_entry_id"],
            ["journal_entries.id"],
            name="fk_reversals_reversal_journal_entry_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "reversal_journal_entry_id", name="uq_reversals_reversal_journal_entry_id"
        ),
        comment="Compensating entries. Large amounts need a second actor before posting.",
    )
    op.create_index("ix_reversals_status", "reversals", ["status"])
    op.create_index(
        "uq_reversals_original_active",
        "reversals",
        ["original_journal_entry_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('proposed', 'posted')"),
    )


def downgrade() -> None:
    op.drop_index("uq_reversals_original_active", table_name="reversals")
    op.drop_index("ix_reversals_status", table_name="reversals")
    op.drop_table("reversals")
