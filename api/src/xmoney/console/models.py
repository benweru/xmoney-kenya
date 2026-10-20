"""Staff identity and an append-only audit log. Separate from wallet users."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from xmoney.db import Base


class StaffUser(Base):
    __tablename__ = "staff_users"
    __table_args__ = (
        CheckConstraint("handle = lower(handle)", name="ck_staff_users_handle_lower"),
        CheckConstraint("handle ~ '^[a-z][a-z0-9_]{2,19}$'", name="ck_staff_users_handle_shape"),
        CheckConstraint("failed_attempts >= 0", name="ck_staff_users_failed_attempts"),
        UniqueConstraint("handle", name="uq_staff_users_handle"),
        {"comment": "Ops staff. Not wallet users. PIN is Argon2id; there is no phone or OTP."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    handle: Mapped[str] = mapped_column(String(20), nullable=False)
    pin_hash: Mapped[str] = mapped_column(Text, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StaffSession(Base):
    __tablename__ = "staff_sessions"
    __table_args__ = (
        CheckConstraint("char_length(token_hash) = 64", name="ck_staff_sessions_hash_len"),
        UniqueConstraint("token_hash", name="uq_staff_sessions_token_hash"),
        Index("ix_staff_sessions_staff_user_id", "staff_user_id"),
        {
            "comment": (
                "Server-side staff sessions. The cookie holds the token; this table its SHA-256."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    staff_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("staff_users.id", name="fk_staff_sessions_staff_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StaffAuditEvent(Base):
    __tablename__ = "staff_audit_events"
    __table_args__ = (
        CheckConstraint("char_length(action) >= 1", name="ck_staff_audit_action"),
        Index("ix_staff_audit_created", "created_at"),
        Index("ix_staff_audit_staff_user_id", "staff_user_id"),
        {"comment": "Append-only log of staff console actions. Rows are never updated."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    staff_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("staff_users.id", name="fk_staff_audit_staff_user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
