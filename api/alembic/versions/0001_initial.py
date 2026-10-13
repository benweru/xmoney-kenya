"""Initial ledger, handles, and immutability checks.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-12

"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Keep these rows aligned with xmoney.ledger.system.SYSTEM_ACCOUNTS.
_SYSTEM_ACCOUNTS = (
    {
        "id": UUID("00000000-0000-4000-8000-000000000001"),
        "code": "system:mpesa_float",
        "name": "M-PESA float",
        "account_type": "asset",
        "normal_side": "debit",
    },
    {
        "id": UUID("00000000-0000-4000-8000-000000000002"),
        "code": "system:mpesa_clearing",
        "name": "M-PESA clearing",
        "account_type": "asset",
        "normal_side": "debit",
    },
    {
        "id": UUID("00000000-0000-4000-8000-000000000003"),
        "code": "system:fees",
        "name": "Fee income",
        "account_type": "income",
        "normal_side": "credit",
    },
    {
        "id": UUID("00000000-0000-4000-8000-000000000004"),
        "code": "system:suspense",
        "name": "Suspense",
        "account_type": "liability",
        "normal_side": "credit",
    },
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("handle", sa.String(length=20), nullable=False),
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("handle = lower(handle)", name="ck_users_handle_lower"),
        sa.CheckConstraint(
            "handle ~ '^[a-z][a-z0-9_]{2,19}$'",
            name="ck_users_handle_shape",
        ),
        sa.CheckConstraint(
            "phone_e164 ~ '^\\+254[17][0-9]{8}$'",
            name="ck_users_phone_e164",
        ),
        sa.UniqueConstraint("handle", name="uq_users_handle"),
        sa.UniqueConstraint("phone_e164", name="uq_users_phone_e164"),
        comment="Registered people. Handles are stored lowercase without the @.",
    )
    op.create_table(
        "ledger_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("normal_side", sa.String(length=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="KES"),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("code = lower(code)", name="ck_ledger_accounts_code_lower"),
        sa.CheckConstraint("currency = 'KES'", name="ck_ledger_accounts_currency_kes"),
        sa.CheckConstraint(
            "(account_type IN ('asset', 'expense') AND normal_side = 'debit') OR "
            "(account_type IN ('liability', 'equity', 'income') AND normal_side = 'credit')",
            name="ck_ledger_accounts_normal_side",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_ledger_accounts_owner_user_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("code", name="uq_ledger_accounts_code"),
        comment="Chart of accounts. Balances are not stored on this table.",
    )
    op.create_index(
        "uq_ledger_accounts_one_owner",
        "ledger_accounts",
        ["owner_user_id"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
    )
    op.create_table(
        "journal_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("external_ref", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 200",
            name="ck_journal_entries_idempotency_len",
        ),
        sa.CheckConstraint(
            "char_length(request_hash) = 64",
            name="ck_journal_entries_hash_len",
        ),
        sa.CheckConstraint(
            "char_length(description) BETWEEN 1 AND 500",
            name="ck_journal_entries_description_len",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_journal_entries_idempotency_key"),
        comment="Immutable journal headers. Idempotency keys compare a hash of the postings.",
    )
    op.create_table(
        "postings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("amount_cents > 0", name="ck_postings_amount_positive"),
        sa.CheckConstraint(
            "direction IN ('debit', 'credit')",
            name="ck_postings_direction",
        ),
        sa.CheckConstraint("line_no >= 1", name="ck_postings_line_no"),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            name="fk_postings_journal_entry_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["ledger_accounts.id"],
            name="fk_postings_account_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("journal_entry_id", "line_no", name="uq_postings_entry_line"),
        comment="Immutable debit and credit lines. Amounts are integer KES cents.",
    )
    op.create_index("ix_postings_account_id", "postings", ["account_id"])
    op.create_index("ix_postings_journal_entry_id", "postings", ["journal_entry_id"])

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION xmoney_reject_ledger_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              RAISE EXCEPTION 'immutable ledger row'
                USING ERRCODE = '55000';
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION xmoney_assert_entry_balanced()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
              target uuid;
              debit_sum bigint;
              credit_sum bigint;
              posting_count integer;
            BEGIN
              IF TG_TABLE_NAME = 'journal_entries' THEN
                target := NEW.id;
              ELSE
                target := COALESCE(NEW.journal_entry_id, OLD.journal_entry_id);
              END IF;

              SELECT
                COALESCE(SUM(amount_cents) FILTER (WHERE direction = 'debit'), 0),
                COALESCE(SUM(amount_cents) FILTER (WHERE direction = 'credit'), 0),
                COUNT(*)
              INTO debit_sum, credit_sum, posting_count
              FROM postings
              WHERE journal_entry_id = target;

              IF posting_count < 2 OR debit_sum <> credit_sum THEN
                RAISE EXCEPTION 'unbalanced journal entry'
                  USING ERRCODE = '23514',
                        DETAIL = 'debits=' || debit_sum
                          || ' credits=' || credit_sum
                          || ' postings=' || posting_count;
              END IF;
              RETURN NULL;
            END;
            $$;
            """
        )
    )
    for table in ("postings", "journal_entries", "ledger_accounts"):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {table}_immutable
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION xmoney_reject_ledger_mutation();
                """
            )
        )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER journal_entries_balanced
            AFTER INSERT ON journal_entries
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION xmoney_assert_entry_balanced();
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER postings_keep_entry_balanced
            AFTER INSERT OR UPDATE OR DELETE ON postings
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION xmoney_assert_entry_balanced();
            """
        )
    )

    accounts = sa.table(
        "ledger_accounts",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("account_type", sa.String),
        sa.column("normal_side", sa.String),
        sa.column("currency", sa.String),
    )
    op.bulk_insert(
        accounts,
        [{**row, "currency": "KES"} for row in _SYSTEM_ACCOUNTS],
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS postings_keep_entry_balanced ON postings"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS journal_entries_balanced ON journal_entries"))
    for table in ("postings", "journal_entries", "ledger_accounts"):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}"))
    op.drop_index("ix_postings_journal_entry_id", table_name="postings")
    op.drop_index("ix_postings_account_id", table_name="postings")
    op.drop_table("postings")
    op.drop_table("journal_entries")
    op.drop_index("uq_ledger_accounts_one_owner", table_name="ledger_accounts")
    op.drop_table("ledger_accounts")
    op.drop_table("users")
    op.execute(sa.text("DROP FUNCTION IF EXISTS xmoney_assert_entry_balanced()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS xmoney_reject_ledger_mutation()"))
