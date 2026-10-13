"""STK top-ups, the callback log, and a trigger that enforces the top-up state machine.

Revision ID: 0004_topups
Revises: 0003_auth
Create Date: 2026-10-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_topups"
down_revision: str | None = "0003_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "topups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wallet_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("merchant_request_id", sa.String(length=64), nullable=True),
        sa.Column("checkout_request_id", sa.String(length=64), nullable=True),
        sa.Column("result_code", sa.Integer(), nullable=True),
        sa.Column("result_desc", sa.String(length=300), nullable=True),
        sa.Column("mpesa_receipt_number", sa.String(length=40), nullable=True),
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.Column("queried_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "amount_cents > 0 AND amount_cents % 100 = 0", name="ck_topups_whole_shillings"
        ),
        sa.CheckConstraint(
            "status IN ('initiated', 'pending', 'succeeded', 'failed', 'expired')",
            name="ck_topups_status",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded') = (journal_entry_id IS NOT NULL)",
            name="ck_topups_succeeded_has_entry",
        ),
        sa.CheckConstraint(
            "status = 'initiated' OR status = 'failed' OR status = 'expired' "
            "OR checkout_request_id IS NOT NULL",
            name="ck_topups_pending_has_checkout",
        ),
        sa.CheckConstraint("char_length(request_hash) = 64", name="ck_topups_hash_len"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_topups_user_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["wallet_account_id"],
            ["ledger_accounts.id"],
            name="fk_topups_wallet_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            name="fk_topups_journal_entry_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_topups_user_idempotency_key"),
        sa.UniqueConstraint("checkout_request_id", name="uq_topups_checkout_request_id"),
        sa.UniqueConstraint("mpesa_receipt_number", name="uq_topups_mpesa_receipt_number"),
        sa.UniqueConstraint("journal_entry_id", name="uq_topups_journal_entry_id"),
        comment="STK Push top-ups: initiated -> pending -> succeeded | failed | expired.",
    )
    op.create_index("ix_topups_status_created", "topups", ["status", "created_at"])
    op.create_table(
        "stk_callbacks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("checkout_request_id", sa.String(length=64), nullable=False),
        sa.Column("topup_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_code", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "disposition IN ('applied', 'duplicate', 'conflict', 'amount_mismatch', 'unmatched')",
            name="ck_stk_callbacks_disposition",
        ),
        sa.ForeignKeyConstraint(
            ["topup_id"], ["topups.id"], name="fk_stk_callbacks_topup_id", ondelete="RESTRICT"
        ),
        comment="Every STK callback as received, and what it did. Duplicates are kept.",
    )
    op.create_index(
        "ix_stk_callbacks_checkout_request_id", "stk_callbacks", ["checkout_request_id"]
    )

    # Keep the transition table aligned with xmoney.payments.state.ALLOWED.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION xmoney_guard_topup()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              IF NEW.user_id <> OLD.user_id
                 OR NEW.wallet_account_id <> OLD.wallet_account_id
                 OR NEW.idempotency_key <> OLD.idempotency_key
                 OR NEW.request_hash <> OLD.request_hash
                 OR NEW.amount_cents <> OLD.amount_cents
                 OR NEW.phone_e164 <> OLD.phone_e164 THEN
                RAISE EXCEPTION 'top-up request fields are immutable'
                  USING ERRCODE = '55000';
              END IF;
              IF OLD.checkout_request_id IS NOT NULL
                 AND NEW.checkout_request_id IS DISTINCT FROM OLD.checkout_request_id THEN
                RAISE EXCEPTION 'top-up checkout_request_id is immutable once set'
                  USING ERRCODE = '55000';
              END IF;
              IF OLD.journal_entry_id IS NOT NULL
                 AND NEW.journal_entry_id IS DISTINCT FROM OLD.journal_entry_id THEN
                RAISE EXCEPTION 'top-up journal_entry_id is immutable once set'
                  USING ERRCODE = '55000';
              END IF;
              IF NEW.status <> OLD.status AND NOT (
                   (OLD.status = 'initiated' AND NEW.status IN ('pending', 'failed', 'expired'))
                OR (OLD.status = 'pending' AND NEW.status IN ('succeeded', 'failed', 'expired'))
                OR (OLD.status = 'expired' AND NEW.status IN ('succeeded', 'failed'))
              ) THEN
                RAISE EXCEPTION 'illegal top-up transition % -> %', OLD.status, NEW.status
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
            CREATE TRIGGER topups_guard
            BEFORE UPDATE ON topups
            FOR EACH ROW
            EXECUTE FUNCTION xmoney_guard_topup();
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER topups_no_delete
            BEFORE DELETE ON topups
            FOR EACH ROW
            EXECUTE FUNCTION xmoney_reject_ledger_mutation();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS topups_no_delete ON topups"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS topups_guard ON topups"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS xmoney_guard_topup()"))
    op.drop_index("ix_stk_callbacks_checkout_request_id", table_name="stk_callbacks")
    op.drop_table("stk_callbacks")
    op.drop_index("ix_topups_status_created", table_name="topups")
    op.drop_table("topups")
