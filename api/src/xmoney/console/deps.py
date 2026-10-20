"""Resolve the staff session cookie. Wallet cookies do not count."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from xmoney.config import get_settings
from xmoney.console.service import StaffActor, authenticate_staff
from xmoney.db import get_db
from xmoney.errors import NotFound

STAFF_COOKIE = "xmoney_staff_session"


def current_staff(request: Request, session: Session = Depends(get_db)) -> StaffActor:
    return authenticate_staff(session, request.cookies.get(STAFF_COOKIE))


def require_console_money_moving() -> None:
    """404 when apply/refund/reverse are off, the same shape as SANDBOX_JOURNAL_ENABLED."""
    if not get_settings().console_money_moving_enabled:
        raise NotFound("not found")
