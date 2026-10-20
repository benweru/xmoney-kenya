"""Versioned P2P fee schedules, and the fee each transfer used.

Revision ID: 0012_fee_schedules
Revises: 0011_cashouts
Create Date: 2026-10-20

"""

from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_fee_schedules"
down_revision: str | None = "0011_cashouts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_ID = "00000000-0000-4000-8000-0000000000f1"
_DEFAULT_BANDS = [
    {"up_to_cents": 10_000, "flat_cents": 0, "rate_bps": 0},
    {"up_to_cents": 100_000, "flat_cents": 100, "rate_bps": 0},
    {"up_to_cents": None, "flat_cents": 200, "rate_bps": 50},
]


def upgrade() -> None:
    op.create_table(
        "fee_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("product", sa.String(length=20), nullable=False),
        sa.Column("free_count_per_calendar_month", sa.Integer(), nullable=False),
        sa.Column(
            "bands",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("version > 0", name="ck_fee_schedules_version_positive"),
        sa.CheckConstraint(
            "free_count_per_calendar_month >= 0",
            name="ck_fee_schedules_free_count",
        ),
        sa.CheckConstraint("product IN ('p2p')", name="ck_fee_schedules_product"),
        sa.UniqueConstraint("version", name="uq_fee_schedules_version"),
        sa.UniqueConstraint("product", "version", name="uq_fee_schedules_product_version"),
        comment="Append-only fee versions. A transfer stores the version it used.",
    )
    op.execute(
        sa.text(
            """
            INSERT INTO fee_schedules (
                id, version, product, free_count_per_calendar_month, bands
            ) VALUES (
                :id, 1, 'p2p', 0, CAST(:bands AS jsonb)
            )
            """
        ).bindparams(
            sa.bindparam("id", UUID(_DEFAULT_ID)),
            sa.bindparam("bands", json.dumps(_DEFAULT_BANDS)),
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER fee_schedules_immutable
            BEFORE UPDATE OR DELETE ON fee_schedules
            FOR EACH ROW
            EXECUTE FUNCTION xmoney_reject_ledger_mutation();
            """
        )
    )
    op.add_column(
        "transfers",
        sa.Column("fee_cents", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "transfers",
        sa.Column("fee_schedule_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "transfers",
        sa.Column(
            "fee_schedule_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_transfers_fee_non_negative",
        "transfers",
        "fee_cents >= 0",
    )
    op.create_check_constraint(
        "ck_transfers_fee_schedule",
        "transfers",
        "(fee_schedule_id IS NULL) = (fee_schedule_version = 0)",
    )
    op.create_foreign_key(
        "fk_transfers_fee_schedule_id",
        "transfers",
        "fee_schedules",
        ["fee_schedule_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_transfers_fee_schedule_id", "transfers", type_="foreignkey")
    op.drop_constraint("ck_transfers_fee_schedule", "transfers", type_="check")
    op.drop_constraint("ck_transfers_fee_non_negative", "transfers", type_="check")
    op.drop_column("transfers", "fee_schedule_version")
    op.drop_column("transfers", "fee_schedule_id")
    op.drop_column("transfers", "fee_cents")
    op.execute(sa.text("DROP TRIGGER IF EXISTS fee_schedules_immutable ON fee_schedules"))
    op.drop_table("fee_schedules")
