"""B2C cash-outs: a hold, then settle or release on the rail result.

Revision ID: 0011_cashouts
Revises: 0010_outbox
Create Date: 2026-10-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_cashouts"
down_revision: str | None = "0010_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cashouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wallet_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("originator_conversation_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("result_code", sa.Integer(), nullable=True),
        sa.Column("result_desc", sa.String(length=300), nullable=True),
        sa.Column("mpesa_receipt_number", sa.String(length=40), nullable=True),
        sa.Column("hold_journal_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("settle_journal_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("release_journal_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "amount_cents > 0 AND amount_cents % 100 = 0", name="ck_cashouts_whole_shillings"
        ),
        sa.CheckConstraint(
            "status IN ('initiated', 'pending', 'succeeded', 'failed', 'expired')",
            name="ck_cashouts_status",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded') = (settle_journal_entry_id IS NOT NULL)",
            name="ck_cashouts_succeeded_has_settle",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (release_journal_entry_id IS NOT NULL)",
            name="ck_cashouts_failed_has_release",
        ),
        sa.CheckConstraint(
            "status IN ('initiated', 'failed') OR conversation_id IS NOT NULL",
            name="ck_cashouts_pending_has_conversation",
        ),
        sa.CheckConstraint("char_length(request_hash) = 64", name="ck_cashouts_hash_len"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_cashouts_user_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["wallet_account_id"],
            ["ledger_accounts.id"],
            name="fk_cashouts_wallet_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["hold_journal_entry_id"],
            ["journal_entries.id"],
            name="fk_cashouts_hold_journal_entry_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["settle_journal_entry_id"],
            ["journal_entries.id"],
            name="fk_cashouts_settle_journal_entry_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["release_journal_entry_id"],
            ["journal_entries.id"],
            name="fk_cashouts_release_journal_entry_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_cashouts_user_idempotency_key"),
        sa.UniqueConstraint(
            "originator_conversation_id", name="uq_cashouts_originator_conversation_id"
        ),
        sa.UniqueConstraint("conversation_id", name="uq_cashouts_conversation_id"),
        sa.UniqueConstraint("mpesa_receipt_number", name="uq_cashouts_mpesa_receipt_number"),
        sa.UniqueConstraint("hold_journal_entry_id", name="uq_cashouts_hold_journal_entry_id"),
        sa.UniqueConstraint("settle_journal_entry_id", name="uq_cashouts_settle_journal_entry_id"),
        sa.UniqueConstraint(
            "release_journal_entry_id", name="uq_cashouts_release_journal_entry_id"
        ),
        comment="B2C cash-outs: hold the wallet, then settle or release on the rail result.",
    )
    op.create_index("ix_cashouts_status_created", "cashouts", ["status", "created_at"])
    op.create_table(
        "b2c_callbacks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("originator_conversation_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("cashout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_code", sa.Integer(), nullable=False),
        sa.Column("timed_out", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("disposition", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "disposition IN ("
            "'applied', 'duplicate', 'conflict', 'amount_mismatch', 'unmatched', 'recorded')",
            name="ck_b2c_callbacks_disposition",
        ),
        sa.ForeignKeyConstraint(
            ["cashout_id"],
            ["cashouts.id"],
            name="fk_b2c_callbacks_cashout_id",
            ondelete="RESTRICT",
        ),
        comment="Every B2C result or timeout callback, and what it did. Duplicates are kept.",
    )
    op.create_index(
        "ix_b2c_callbacks_originator_conversation_id",
        "b2c_callbacks",
        ["originator_conversation_id"],
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION xmoney_guard_cashout()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              IF NEW.user_id <> OLD.user_id
                 OR NEW.wallet_account_id <> OLD.wallet_account_id
                 OR NEW.idempotency_key <> OLD.idempotency_key
                 OR NEW.request_hash <> OLD.request_hash
                 OR NEW.amount_cents <> OLD.amount_cents
                 OR NEW.phone_e164 <> OLD.phone_e164
                 OR NEW.originator_conversation_id <> OLD.originator_conversation_id
                 OR NEW.hold_journal_entry_id <> OLD.hold_journal_entry_id THEN
                RAISE EXCEPTION 'cash-out request fields are immutable'
                  USING ERRCODE = '55000';
              END IF;
              IF OLD.conversation_id IS NOT NULL
                 AND NEW.conversation_id IS DISTINCT FROM OLD.conversation_id THEN
                RAISE EXCEPTION 'cash-out conversation_id is immutable once set'
                  USING ERRCODE = '55000';
              END IF;
              IF OLD.settle_journal_entry_id IS NOT NULL
                 AND NEW.settle_journal_entry_id IS DISTINCT FROM OLD.settle_journal_entry_id THEN
                RAISE EXCEPTION 'cash-out settle_journal_entry_id is immutable once set'
                  USING ERRCODE = '55000';
              END IF;
              IF OLD.release_journal_entry_id IS NOT NULL
                 AND NEW.release_journal_entry_id IS DISTINCT FROM OLD.release_journal_entry_id THEN
                RAISE EXCEPTION 'cash-out release_journal_entry_id is immutable once set'
                  USING ERRCODE = '55000';
              END IF;
              IF NEW.status <> OLD.status AND NOT (
                   (OLD.status = 'initiated' AND NEW.status IN ('pending', 'failed'))
                OR (OLD.status = 'pending' AND NEW.status IN ('succeeded', 'failed', 'expired'))
                OR (OLD.status = 'expired' AND NEW.status IN ('succeeded', 'failed'))
              ) THEN
                RAISE EXCEPTION 'illegal cash-out transition % -> %', OLD.status, NEW.status
                  USING ERRCODE = '55000';
              END IF;
              RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER cashouts_guard
            BEFORE UPDATE ON cashouts
            FOR EACH ROW
            EXECUTE FUNCTION xmoney_guard_cashout();
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER cashouts_no_delete
            BEFORE DELETE ON cashouts
            FOR EACH ROW
            EXECUTE FUNCTION xmoney_reject_ledger_mutation();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS cashouts_no_delete ON cashouts"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS cashouts_guard ON cashouts"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS xmoney_guard_cashout()"))
    op.drop_index("ix_b2c_callbacks_originator_conversation_id", table_name="b2c_callbacks")
    op.drop_table("b2c_callbacks")
    op.drop_index("ix_cashouts_status_created", table_name="cashouts")
    op.drop_table("cashouts")
