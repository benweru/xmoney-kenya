"""FastAPI dependency that resolves the session cookie to a signed-in user."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from xmoney.auth.service import SessionUser, authenticate
from xmoney.db import get_db

SESSION_COOKIE = "xmoney_session"


def current_user(request: Request, session: Session = Depends(get_db)) -> SessionUser:
    return authenticate(session, request.cookies.get(SESSION_COOKIE))
