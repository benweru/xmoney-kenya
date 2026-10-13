"""Stored sandbox messages, keyed by the phone they would have been texted to."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from xmoney.db import Base


class SandboxMessage(Base):
    __tablename__ = "sandbox_inbox"
    __table_args__ = (
        Index("ix_sandbox_inbox_phone_created", "phone_e164", "created_at"),
        {"comment": "Sandbox stand-in for SMS. Readable by anyone who knows the phone."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    phone_e164: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
