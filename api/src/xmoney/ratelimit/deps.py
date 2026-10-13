"""FastAPI dependencies that apply a Limit per client IP or per signed-in user."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from xmoney.auth.deps import current_user
from xmoney.auth.service import SessionUser
from xmoney.config import get_settings
from xmoney.db import get_db
from xmoney.ratelimit.service import Limit, enforce


def client_ip(request: Request) -> str:
    """The caller's IP, read from X-Forwarded-For only as far as trusted proxies wrote it.

    Each proxy appends the address it received the request from, so with N
    trusted proxies the client is the Nth entry from the right. Anything to
    the left of that was written by the client and is ignored.
    """
    hops = get_settings().trusted_proxy_hops
    if hops > 0:
        forwarded = [
            part.strip()
            for part in request.headers.get("x-forwarded-for", "").split(",")
            if part.strip()
        ]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.client.host if request.client else "unknown"


def limit_by_ip(limit: Limit) -> Callable[..., None]:
    def dependency(request: Request, session: Session = Depends(get_db)) -> None:
        enforce(session, limit, client_ip(request))

    return dependency


def limit_by_user(limit: Limit) -> Callable[..., None]:
    def dependency(
        user: SessionUser = Depends(current_user), session: Session = Depends(get_db)
    ) -> None:
        enforce(session, limit, str(user.user_id))

    return dependency
