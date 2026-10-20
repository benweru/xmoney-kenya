"""Staff users, staff sessions, and an append-only audit log for the console.

Revision ID: 0016_staff_console
Revises: 0015_reversals
Create Date: 2026-10-20

"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_staff_console"
down_revision: str | None = "0015_reversals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at(name: str = "created_at") -> sa.Column[datetime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def upgrade() -> None:
    op.create_table(
        "staff_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("handle", sa.String(length=20), nullable=False),
        sa.Column("pin_hash", sa.Text(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _created_at("updated_at"),
        sa.CheckConstraint("handle = lower(handle)", name="ck_staff_users_handle_lower"),
        sa.CheckConstraint("handle ~ '^[a-z][a-z0-9_]{2,19}$'", name="ck_staff_users_handle_shape"),
        sa.CheckConstraint("failed_attempts >= 0", name="ck_staff_users_failed_attempts"),
        sa.UniqueConstraint("handle", name="uq_staff_users_handle"),
        comment="Ops staff. Not wallet users. PIN is Argon2id; there is no phone or OTP.",
    )
    op.create_table(
        "staff_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("staff_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("char_length(token_hash) = 64", name="ck_staff_sessions_hash_len"),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name="fk_staff_sessions_staff_user_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_staff_sessions_token_hash"),
        comment="Server-side staff sessions. The cookie holds the token; this table its SHA-256.",
    )
    op.create_index("ix_staff_sessions_staff_user_id", "staff_sessions", ["staff_user_id"])
    op.create_table(
        "staff_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("staff_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=80), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=False),
        _created_at(),
        sa.CheckConstraint("char_length(action) >= 1", name="ck_staff_audit_action"),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name="fk_staff_audit_staff_user_id",
            ondelete="RESTRICT",
        ),
        comment="Append-only log of staff console actions. Rows are never updated.",
    )
    op.create_index("ix_staff_audit_created", "staff_audit_events", ["created_at"])
    op.create_index("ix_staff_audit_staff_user_id", "staff_audit_events", ["staff_user_id"])


def downgrade() -> None:
    op.drop_index("ix_staff_audit_staff_user_id", table_name="staff_audit_events")
    op.drop_index("ix_staff_audit_created", table_name="staff_audit_events")
    op.drop_table("staff_audit_events")
    op.drop_index("ix_staff_sessions_staff_user_id", table_name="staff_sessions")
    op.drop_table("staff_sessions")
    op.drop_table("staff_users")
