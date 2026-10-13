"""Write and read sandbox messages. Callers own the transaction."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from xmoney.inbox.models import SandboxMessage


def deliver(session: Session, *, phone_e164: str, body: str) -> None:
    session.add(SandboxMessage(id=uuid4(), phone_e164=phone_e164, body=body))


def recent_messages(session: Session, phone_e164: str, limit: int = 20) -> Sequence[SandboxMessage]:
    return session.scalars(
        select(SandboxMessage)
        .where(SandboxMessage.phone_e164 == phone_e164)
        .order_by(SandboxMessage.created_at.desc(), SandboxMessage.id.desc())
        .limit(limit)
    ).all()
