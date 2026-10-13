"""Index postings for keyset-paginated wallet history.

The composite index also serves every account_id lookup the single-column
index did, so that one is dropped.

Revision ID: 0006_posting_history_index
Revises: 0005_transfers
Create Date: 2026-10-13

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_posting_history_index"
down_revision: str | None = "0005_transfers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_postings_account_history",
        "postings",
        ["account_id", "created_at", "journal_entry_id"],
    )
    op.drop_index("ix_postings_account_id", table_name="postings")


def downgrade() -> None:
    op.create_index("ix_postings_account_id", "postings", ["account_id"])
    op.drop_index("ix_postings_account_history", table_name="postings")
