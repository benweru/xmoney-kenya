"""Suspense items: unmatched value parked, then applied or refunded.

Revision ID: 0014_suspense
Revises: 0013_recon
Create Date: 2026-10-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_suspense"
down_revision: str | None = "0013_recon"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "suspense_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("recon_break_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("open_reason", sa.String(length=500), nullable=False),
        sa.Column("resolve_reason", sa.String(length=500), nullable=True),
        sa.Column("open_journal_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resolve_journal_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("wallet_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_cents > 0", name="ck_suspense_amount_positive"),
        sa.CheckConstraint(
            "status IN ('open', 'applied', 'refunded')",
            name="ck_suspense_status",
        ),
        sa.CheckConstraint(
            "(status = 'open') = (resolve_journal_entry_id IS NULL)",
            name="ck_suspense_open_unresolved",
        ),
        sa.CheckConstraint(
            "(status = 'applied') = (wallet_account_id IS NOT NULL)",
            name="ck_suspense_applied_has_wallet",
        ),
        sa.CheckConstraint(
            "status = 'open' OR resolve_reason IS NOT NULL",
            name="ck_suspense_resolved_has_reason",
        ),
        sa.ForeignKeyConstraint(
            ["recon_break_id"],
            ["recon_breaks.id"],
            name="fk_suspense_recon_break_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["open_journal_entry_id"],
            ["journal_entries.id"],
            name="fk_suspense_open_journal_entry_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolve_journal_entry_id"],
            ["journal_entries.id"],
            name="fk_suspense_resolve_journal_entry_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["wallet_account_id"],
            ["ledger_accounts.id"],
            name="fk_suspense_wallet_account_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("open_journal_entry_id", name="uq_suspense_open_journal"),
        sa.UniqueConstraint("resolve_journal_entry_id", name="uq_suspense_resolve_journal"),
        comment="Unmatched value parked in system:suspense, then applied or refunded.",
    )
    op.create_index(
        "uq_suspense_open_break",
        "suspense_items",
        ["recon_break_id"],
        unique=True,
        postgresql_where=sa.text("recon_break_id IS NOT NULL AND status = 'open'"),
    )
    op.create_index("ix_suspense_status", "suspense_items", ["status"])


def downgrade() -> None:
    op.drop_index("ix_suspense_status", table_name="suspense_items")
    op.drop_index("uq_suspense_open_break", table_name="suspense_items")
    op.drop_table("suspense_items")
