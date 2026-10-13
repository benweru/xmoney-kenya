"""Read the sandbox inbox for a phone. This replaces SMS in the open demo."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from xmoney.config import get_settings
from xmoney.db import get_db
from xmoney.errors import SandboxViolation
from xmoney.identity.validators import normalize_phone
from xmoney.inbox.service import recent_messages
from xmoney.ratelimit.deps import limit_by_ip
from xmoney.ratelimit.service import READ_INBOX

router = APIRouter(tags=["sandbox"])


class InboxMessageOut(BaseModel):
    body: str
    created_at: datetime


@router.get(
    "/sandbox/inbox",
    response_model=list[InboxMessageOut],
    dependencies=[Depends(limit_by_ip(READ_INBOX))],
)
def read_inbox(phone: str, session: Session = Depends(get_db)) -> list[InboxMessageOut]:
    """Newest first. Anyone can read any phone's inbox, which is only acceptable in a sandbox."""
    if get_settings().sandbox_mode is not True:
        raise SandboxViolation("the sandbox inbox is disabled outside sandbox mode")
    messages = recent_messages(session, normalize_phone(phone))
    return [InboxMessageOut(body=m.body, created_at=m.created_at) for m in messages]
