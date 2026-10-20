"""Resolve the staff session cookie. Wallet cookies do not count."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from xmoney.console.service import StaffActor, authenticate_staff
from xmoney.db import get_db

STAFF_COOKIE = "xmoney_staff_session"


def current_staff(request: Request, session: Session = Depends(get_db)) -> StaffActor:
    return authenticate_staff(session, request.cookies.get(STAFF_COOKIE))
