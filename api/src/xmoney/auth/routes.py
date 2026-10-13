"""Sign-in, sign-out, and the current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from xmoney.auth.deps import SESSION_COOKIE, current_user
from xmoney.auth.schemas import ChallengeOut, MeOut, SignInIn, VerifyIn
from xmoney.auth.service import SessionUser, authenticate, sign_out, start_sign_in, verify_sign_in
from xmoney.config import get_settings
from xmoney.db import get_db

router = APIRouter(tags=["auth"])


@router.post("/auth/sign-in", response_model=ChallengeOut)
def sign_in(body: SignInIn, session: Session = Depends(get_db)) -> ChallengeOut:
    """Check phone and PIN. On success a one-time code goes to the sandbox inbox."""
    challenge = start_sign_in(session, phone=body.phone, pin=body.pin)
    return ChallengeOut(challenge_id=challenge.challenge_id, expires_at=challenge.expires_at)


@router.post("/auth/verify", response_model=MeOut)
def verify(body: VerifyIn, response: Response, session: Session = Depends(get_db)) -> MeOut:
    """Exchange the one-time code for an httpOnly session cookie."""
    issued = verify_sign_in(session, challenge_id=body.challenge_id, code=body.code)
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return _me(authenticate(session, issued.token))


@router.post("/auth/sign-out", status_code=204)
def sign_out_route(request: Request, session: Session = Depends(get_db)) -> Response:
    sign_out(session, request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=MeOut)
def me(user: SessionUser = Depends(current_user)) -> MeOut:
    return _me(user)


def _me(user: SessionUser) -> MeOut:
    return MeOut(
        user_id=user.user_id,
        handle=user.handle,
        phone=user.phone_e164,
        wallet_account_id=user.wallet_account_id,
    )
