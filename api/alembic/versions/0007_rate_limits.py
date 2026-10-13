"""Fixed-window rate-limit counters for the open public demo.

Revision ID: 0007_rate_limits
Revises: 0006_posting_history_index
Create Date: 2026-10-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_rate_limits"
down_revision: str | None = "0006_posting_history_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_hits",
        sa.Column("bucket", sa.String(length=80), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("bucket", "window_start"),
        comment="One row per bucket per window. Buckets hold hashes, never raw IPs.",
    )


def downgrade() -> None:
    op.drop_table("rate_limit_hits")
