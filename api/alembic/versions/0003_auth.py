"""PIN credentials, one-time sign-in codes, sessions, and the sandbox inbox.

Revision ID: 0003_auth
Revises: 0002_seal_ledger_entries
Create Date: 2026-10-13

"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_auth"
down_revision: str | None = "0002_seal_ledger_entries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at(name: str = "created_at") -> sa.Column[datetime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def upgrade() -> None:
    op.create_table(
        "user_pins",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pin_hash", sa.Text(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        _created_at("updated_at"),
        sa.CheckConstraint("failed_attempts >= 0", name="ck_user_pins_failed_attempts"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_pins_user_id", ondelete="CASCADE"
        ),
        comment="Argon2id PIN hashes and the wrong-PIN counter behind the lockout.",
    )
    op.create_table(
        "otp_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("char_length(code_hash) = 64", name="ck_otp_challenges_hash_len"),
        sa.CheckConstraint("attempts >= 0", name="ck_otp_challenges_attempts"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_otp_challenges_user_id", ondelete="CASCADE"
        ),
        comment="One-time sign-in codes, issued after a correct PIN.",
    )
    op.create_index("ix_otp_challenges_user_id", "otp_challenges", ["user_id"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("char_length(token_hash) = 64", name="ck_auth_sessions_hash_len"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_auth_sessions_user_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        comment="Server-side sessions. The cookie holds the token; this table its SHA-256.",
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "sandbox_inbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column("body", sa.String(length=320), nullable=False),
        _created_at(),
        comment="Sandbox stand-in for SMS. Readable by anyone who knows the phone.",
    )
    op.create_index("ix_sandbox_inbox_phone_created", "sandbox_inbox", ["phone_e164", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_sandbox_inbox_phone_created", table_name="sandbox_inbox")
    op.drop_table("sandbox_inbox")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_otp_challenges_user_id", table_name="otp_challenges")
    op.drop_table("otp_challenges")
    op.drop_table("user_pins")
