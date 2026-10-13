"""Seal journal entries at commit and block TRUNCATE on ledger tables.

Revision ID: 0002_seal_ledger_entries
Revises: 0001_initial
Create Date: 2026-10-13

Row triggers in 0001 block UPDATE and DELETE, but two gaps remained:

* A later transaction could INSERT a balanced pair of postings into an entry
  that had already committed, silently changing history.
* TRUNCATE does not fire row triggers, so it emptied the ledger.

Postings may now only be inserted in the transaction that created their
entry. Postgres has no portable "row created by my transaction" test that also
works inside savepoints, so this compares the entry's created_at to
transaction_timestamp(), and a BEFORE INSERT trigger stamps created_at so a
client cannot choose it. TRUNCATE is refused unless the session sets
`xmoney.allow_truncate = on`, which only the test suite does.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_seal_ledger_entries"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEDGER_TABLES = ("postings", "journal_entries", "ledger_accounts")


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION xmoney_stamp_created_at()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              NEW.created_at := transaction_timestamp();
              RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION xmoney_posting_requires_open_entry()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM journal_entries
                WHERE id = NEW.journal_entry_id
                  AND created_at = transaction_timestamp()
              ) THEN
                RAISE EXCEPTION
                  'postings can only be added in the transaction that created their entry'
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
            CREATE OR REPLACE FUNCTION xmoney_reject_ledger_truncate()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              IF current_setting('xmoney.allow_truncate', true) = 'on' THEN
                RETURN NULL;
              END IF;
              RAISE EXCEPTION 'immutable ledger table %', TG_TABLE_NAME
                USING ERRCODE = '55000';
            END;
            $$;
            """
        )
    )
    for table in ("journal_entries", "postings"):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {table}_stamp_created_at
                BEFORE INSERT ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION xmoney_stamp_created_at();
                """
            )
        )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER postings_require_open_entry
            BEFORE INSERT ON postings
            FOR EACH ROW
            EXECUTE FUNCTION xmoney_posting_requires_open_entry();
            """
        )
    )
    for table in _LEDGER_TABLES:
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {table}_no_truncate
                BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT
                EXECUTE FUNCTION xmoney_reject_ledger_truncate();
                """
            )
        )


def downgrade() -> None:
    for table in _LEDGER_TABLES:
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS postings_require_open_entry ON postings"))
    for table in ("journal_entries", "postings"):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {table}_stamp_created_at ON {table}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS xmoney_reject_ledger_truncate()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS xmoney_posting_requires_open_entry()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS xmoney_stamp_created_at()"))
