"""Sign-in: phone and PIN, then a one-time code from the sandbox inbox, then a session.

Each step owns its transaction. A wrong PIN or code is counted and committed
before the error is raised, so the counter cannot be reset by the failure. The
credential and challenge rows are locked while they are checked, so parallel
guesses are counted one by one.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from xmoney.auth.models import AuthSession, OtpChallenge, UserPin
from xmoney.auth.pins import burn_verify, hash_pin, needs_rehash, verify_pin
from xmoney.config import get_settings
from xmoney.db import release_read_transaction
from xmoney.errors import (
    AccountLocked,
    InvalidCredentials,
    InvalidOtp,
    InvalidPhone,
    NotAuthenticated,
)
from xmoney.identity.models import User
from xmoney.identity.validators import normalize_phone
from xmoney.inbox.service import deliver
from xmoney.ledger.models import LedgerAccount

_OTP_DIGITS = 6


@dataclass(frozen=True)
class SignInChallenge:
    challenge_id: UUID
    expires_at: datetime


@dataclass(frozen=True)
class IssuedSession:
    token: str
    user_id: UUID
    expires_at: datetime


@dataclass(frozen=True)
class SessionUser:
    session_id: UUID
    user_id: UUID
    handle: str
    phone_e164: str
    wallet_account_id: UUID


def start_sign_in(
    session: Session, *, phone: str, pin: str, now: datetime | None = None
) -> SignInChallenge:
    """Check the PIN and text a one-time code to the sandbox inbox."""
    settings = get_settings()
    now = now or datetime.now(UTC)
    try:
        normalized = normalize_phone(phone)
    except InvalidPhone:
        normalized = None
    release_read_transaction(session)

    locked_until: datetime | None = None
    challenge: SignInChallenge | None = None
    with session.begin():
        row = (
            session.execute(
                select(User, UserPin)
                .join(UserPin, UserPin.user_id == User.id)
                .where(User.phone_e164 == normalized)
                .with_for_update(of=UserPin)
            ).first()
            if normalized is not None
            else None
        )
        if row is None:
            burn_verify(pin)
        else:
            user, credential = row
            if credential.locked_until is not None and credential.locked_until > now:
                locked_until = credential.locked_until
            elif verify_pin(credential.pin_hash, pin):
                credential.failed_attempts = 0
                credential.locked_until = None
                credential.updated_at = now
                if needs_rehash(credential.pin_hash):
                    credential.pin_hash = hash_pin(pin)
                challenge = _issue_challenge(session, user, now, settings.otp_ttl_seconds)
            else:
                credential.failed_attempts += 1
                credential.updated_at = now
                if credential.failed_attempts >= settings.pin_max_attempts:
                    credential.failed_attempts = 0
                    credential.locked_until = now + timedelta(minutes=settings.pin_lockout_minutes)
                    locked_until = credential.locked_until

    if locked_until is not None:
        raise AccountLocked(
            f"too many wrong PINs; try again after {locked_until.isoformat(timespec='seconds')}"
        )
    if challenge is None:
        raise InvalidCredentials("phone or PIN is incorrect")
    return challenge


def verify_sign_in(
    session: Session, *, challenge_id: UUID, code: str, now: datetime | None = None
) -> IssuedSession:
    """Exchange a one-time code for a session. Each code works once."""
    settings = get_settings()
    now = now or datetime.now(UTC)
    release_read_transaction(session)

    issued: IssuedSession | None = None
    with session.begin():
        challenge = session.scalar(
            select(OtpChallenge).where(OtpChallenge.id == challenge_id).with_for_update()
        )
        usable = (
            challenge is not None
            and challenge.consumed_at is None
            and challenge.expires_at > now
            and challenge.attempts < settings.otp_max_attempts
        )
        if challenge is not None and usable:
            challenge.attempts += 1
            if hmac.compare_digest(challenge.code_hash, _code_hash(challenge.id, code)):
                challenge.consumed_at = now
                issued = _open_session(session, challenge.user_id, now)
    if issued is None:
        raise InvalidOtp("the code is wrong, expired, or already used; sign in again")
    return issued


def authenticate(session: Session, token: str | None, now: datetime | None = None) -> SessionUser:
    if not token:
        raise NotAuthenticated("sign in first")
    now = now or datetime.now(UTC)
    row = session.execute(
        select(AuthSession, User, LedgerAccount)
        .join(User, User.id == AuthSession.user_id)
        .join(LedgerAccount, LedgerAccount.owner_user_id == User.id)
        .where(
            AuthSession.token_hash == _token_hash(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    ).first()
    if row is None:
        raise NotAuthenticated("session is missing, expired, or signed out")
    auth_session, user, wallet = row
    return SessionUser(
        session_id=auth_session.id,
        user_id=user.id,
        handle=user.handle,
        phone_e164=user.phone_e164,
        wallet_account_id=wallet.id,
    )


def sign_out(session: Session, token: str | None, now: datetime | None = None) -> None:
    if not token:
        return
    now = now or datetime.now(UTC)
    release_read_transaction(session)
    with session.begin():
        found = session.scalar(
            select(AuthSession)
            .where(AuthSession.token_hash == _token_hash(token), AuthSession.revoked_at.is_(None))
            .with_for_update()
        )
        if found is not None:
            found.revoked_at = now


def _issue_challenge(session: Session, user: User, now: datetime, ttl: int) -> SignInChallenge:
    challenge_id = uuid4()
    code = f"{secrets.randbelow(10**_OTP_DIGITS):0{_OTP_DIGITS}d}"
    expires_at = now + timedelta(seconds=ttl)
    session.add(
        OtpChallenge(
            id=challenge_id,
            user_id=user.id,
            code_hash=_code_hash(challenge_id, code),
            expires_at=expires_at,
        )
    )
    deliver(
        session,
        phone_e164=user.phone_e164,
        body=(
            f"X Money sandbox: your sign-in code is {code}. "
            f"It expires in {ttl // 60} minutes. Never share it."
        ),
    )
    return SignInChallenge(challenge_id=challenge_id, expires_at=expires_at)


def _open_session(session: Session, user_id: UUID, now: datetime) -> IssuedSession:
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=get_settings().session_ttl_minutes)
    session.add(
        AuthSession(
            id=uuid4(),
            user_id=user_id,
            token_hash=_token_hash(token),
            expires_at=expires_at,
        )
    )
    return IssuedSession(token=token, user_id=user_id, expires_at=expires_at)


def _code_hash(challenge_id: UUID, code: object) -> str:
    raw = f"{challenge_id}:{code if isinstance(code, str) else ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
