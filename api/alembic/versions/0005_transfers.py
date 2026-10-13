"""P2P transfers between wallets.

Revision ID: 0005_transfers
Revises: 0004_topups
Create Date: 2026-10-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_transfers"
down_revision: str | None = "0004_topups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transfers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sender_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.String(length=140), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("amount_cents > 0", name="ck_transfers_amount_positive"),
        sa.CheckConstraint("sender_user_id <> recipient_user_id", name="ck_transfers_not_self"),
        sa.CheckConstraint("char_length(request_hash) = 64", name="ck_transfers_hash_len"),
        sa.ForeignKeyConstraint(
            ["sender_user_id"],
            ["users.id"],
            name="fk_transfers_sender_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name="fk_transfers_recipient_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            name="fk_transfers_journal_entry_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "sender_user_id", "idempotency_key", name="uq_transfers_sender_idempotency_key"
        ),
        sa.UniqueConstraint("journal_entry_id", name="uq_transfers_journal_entry_id"),
        comment="P2P sends. Immutable; each one points at the journal entry that moved it.",
    )
    op.create_index("ix_transfers_recipient_user_id", "transfers", ["recipient_user_id"])
    op.execute(
        sa.text(
            """
            CREATE TRIGGER transfers_immutable
            BEFORE UPDATE OR DELETE ON transfers
            FOR EACH ROW
            EXECUTE FUNCTION xmoney_reject_ledger_mutation();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS transfers_immutable ON transfers"))
    op.drop_index("ix_transfers_recipient_user_id", table_name="transfers")
    op.drop_table("transfers")
