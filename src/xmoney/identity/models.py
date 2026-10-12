"""People who can be paid at an @handle."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from xmoney.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("handle = lower(handle)", name="ck_users_handle_lower"),
        CheckConstraint(
            "handle ~ '^[a-z][a-z0-9_]{2,19}$'",
            name="ck_users_handle_shape",
        ),
        CheckConstraint(
            "phone_e164 ~ '^\\+254[17][0-9]{8}$'",
            name="ck_users_phone_e164",
        ),
        UniqueConstraint("handle", name="uq_users_handle"),
        UniqueConstraint("phone_e164", name="uq_users_phone_e164"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    handle: Mapped[str] = mapped_column(String(20), nullable=False)
    phone_e164: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
