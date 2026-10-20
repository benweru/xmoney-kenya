"""Quieted recon breaks after a linked suspense item closes.

Revision ID: 0017_recon_break_quieted
Revises: 0016_staff_console
Create Date: 2026-10-21

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_recon_break_quieted"
down_revision: str | None = "0016_staff_console"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recon_breaks",
        sa.Column("quieted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_recon_breaks_quieted_subject",
        "recon_breaks",
        ["subject_type", "subject_id"],
        postgresql_where=sa.text("quieted_at IS NOT NULL AND subject_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_recon_breaks_quieted_subject", table_name="recon_breaks")
    op.drop_column("recon_breaks", "quieted_at")
