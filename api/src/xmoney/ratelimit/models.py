"""Fixed-window request counters, shared by every API instance through Postgres."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from xmoney.db import Base


class RateLimitHit(Base):
    __tablename__ = "rate_limit_hits"
    __table_args__ = (
        {"comment": "One row per bucket per window. Buckets hold hashes, never raw IPs."},
    )

    bucket: Mapped[str] = mapped_column(String(80), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, nullable=False)
