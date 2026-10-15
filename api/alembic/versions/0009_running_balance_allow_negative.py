"""Skip locking system accounts; keep running balances on wallets.

Revision ID: 0009_wallet_running_totals
Revises: 0008_stk_callback_recorded
Create Date: 2026-10-15

Customer wallets cannot go negative, so they stay SELECT … FOR UPDATE on post
and get a trigger-maintained running debit/credit. System accounts such as
system:mpesa_float may go negative; locking them serialized every top-up.
Their balances stay a SUM of postings (the M3 reconciler will check wallets).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_wallet_running_totals"
down_revision: str | None = "0008_stk_callback_recorded"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ledger_accounts",
        sa.Column(
            "allow_negative",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "ledger_accounts",
        sa.Column(
            "running_debit_cents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "ledger_accounts",
        sa.Column(
            "running_credit_cents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "ck_ledger_accounts_running_non_negative",
        "ledger_accounts",
        "running_debit_cents >= 0 AND running_credit_cents >= 0",
    )
    op.execute(sa.text("ALTER TABLE ledger_accounts DISABLE TRIGGER ledger_accounts_immutable"))
    op.execute(
        sa.text(
            """
            UPDATE ledger_accounts
            SET allow_negative = true
            WHERE owner_user_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE ledger_accounts AS a
            SET
              running_debit_cents = COALESCE(
                (SELECT SUM(p.amount_cents) FROM postings p
                 WHERE p.account_id = a.id AND p.direction = 'debit'),
                0
              ),
              running_credit_cents = COALESCE(
                (SELECT SUM(p.amount_cents) FROM postings p
                 WHERE p.account_id = a.id AND p.direction = 'credit'),
                0
              )
            WHERE NOT a.allow_negative
            """
        )
    )
    op.execute(sa.text("ALTER TABLE ledger_accounts ENABLE TRIGGER ledger_accounts_immutable"))
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION xmoney_reject_ledger_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              IF TG_TABLE_NAME = 'ledger_accounts'
                 AND TG_OP = 'UPDATE'
                 AND current_setting('xmoney.maintain_running_balance', true) = 'on'
                 AND NEW.id IS NOT DISTINCT FROM OLD.id
                 AND NEW.code IS NOT DISTINCT FROM OLD.code
                 AND NEW.name IS NOT DISTINCT FROM OLD.name
                 AND NEW.account_type IS NOT DISTINCT FROM OLD.account_type
                 AND NEW.normal_side IS NOT DISTINCT FROM OLD.normal_side
                 AND NEW.currency IS NOT DISTINCT FROM OLD.currency
                 AND NEW.owner_user_id IS NOT DISTINCT FROM OLD.owner_user_id
                 AND NEW.created_at IS NOT DISTINCT FROM OLD.created_at
                 AND NEW.allow_negative IS NOT DISTINCT FROM OLD.allow_negative
              THEN
                RETURN NEW;
              END IF;
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
            CREATE OR REPLACE FUNCTION xmoney_apply_running_balance()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              PERFORM set_config('xmoney.maintain_running_balance', 'on', true);
              IF NEW.direction = 'debit' THEN
                UPDATE ledger_accounts
                   SET running_debit_cents = running_debit_cents + NEW.amount_cents
                 WHERE id = NEW.account_id AND NOT allow_negative;
              ELSE
                UPDATE ledger_accounts
                   SET running_credit_cents = running_credit_cents + NEW.amount_cents
                 WHERE id = NEW.account_id AND NOT allow_negative;
              END IF;
              RETURN NULL;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER postings_apply_running_balance
            AFTER INSERT ON postings
            FOR EACH ROW
            EXECUTE FUNCTION xmoney_apply_running_balance();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS postings_apply_running_balance ON postings"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS xmoney_apply_running_balance()"))
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
    op.drop_constraint("ck_ledger_accounts_running_non_negative", "ledger_accounts", type_="check")
    op.drop_column("ledger_accounts", "running_credit_cents")
    op.drop_column("ledger_accounts", "running_debit_cents")
    op.drop_column("ledger_accounts", "allow_negative")
