"""Staff PIN sessions, lookups, and an append-only audit log.

Staff are not wallet users. A correct PIN issues a session at once: there is no
OTP, because the sandbox inbox is a customer surface. Lockout matches ADR 004.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from xmoney.auth.pins import burn_verify, hash_pin, needs_rehash, require_new_pin, verify_pin
from xmoney.config import get_settings
from xmoney.console.models import StaffAuditEvent, StaffSession, StaffUser
from xmoney.db import release_read_transaction
from xmoney.errors import (
    AccountLocked,
    InvalidCredentials,
    InvalidHandle,
    InvalidOutbox,
    NotAuthenticated,
    NotFound,
    OutboxJobNotFound,
    UserNotFound,
)
from xmoney.history.service import HistoryPage, wallet_history
from xmoney.identity.models import User
from xmoney.identity.service import lookup_handle
from xmoney.identity.validators import HANDLE_RE
from xmoney.ledger.models import JournalEntry, LedgerAccount, Posting
from xmoney.ledger.service import AccountBalance, get_balance
from xmoney.outbox.models import OutboxJob
from xmoney.outbox.service import OutboxError
from xmoney.outbox.service import dead_jobs as list_dead_jobs
from xmoney.outbox.service import replay as replay_dead_job
from xmoney.recon.models import ReconBreak, ReconRun
from xmoney.suspense.models import SuspenseItem

DEFAULT_STAFF_HANDLE = "ops"
DEFAULT_STAFF_PIN = "2580"


@dataclass(frozen=True)
class IssuedStaffSession:
    token: str
    staff_user_id: UUID
    expires_at: datetime


@dataclass(frozen=True)
class StaffActor:
    session_id: UUID
    staff_user_id: UUID
    handle: str


@dataclass(frozen=True)
class ConsoleUser:
    user_id: UUID
    handle: str
    phone_e164: str
    wallet_account_id: UUID
    created_at: datetime
    balance: AccountBalance


@dataclass(frozen=True)
class JournalView:
    entry: JournalEntry
    lines: list[tuple[Posting, LedgerAccount]]


@dataclass(frozen=True)
class LatestRecon:
    run: ReconRun | None
    breaks: list[ReconBreak]


def seed_staff_user(session: Session, *, handle: str | None = None, pin: str | None = None) -> bool:
    """Create the demo staff user unless it exists. Returns False if already there."""
    raw_handle = handle if handle is not None else os.environ.get("DEMO_STAFF_HANDLE")
    handle = _staff_handle(raw_handle or DEFAULT_STAFF_HANDLE)
    raw_pin = pin if pin is not None else os.environ.get("DEMO_STAFF_PIN", DEFAULT_STAFF_PIN)
    if raw_pin == "":
        return False
    pin_value = require_new_pin(raw_pin)
    release_read_transaction(session)
    with session.begin():
        existing = session.scalar(select(StaffUser.id).where(StaffUser.handle == handle))
        if existing is not None:
            return False
        session.add(StaffUser(id=uuid4(), handle=handle, pin_hash=hash_pin(pin_value)))
    return True


def sign_in_staff(
    session: Session, *, handle: str, pin: str, now: datetime | None = None
) -> IssuedStaffSession:
    """Check the staff PIN and open a session. Wrong guesses are counted and committed."""
    settings = get_settings()
    now = now or datetime.now(UTC)
    try:
        normalized = _staff_handle(handle)
    except InvalidHandle:
        normalized = None
    release_read_transaction(session)

    locked_until: datetime | None = None
    issued: IssuedStaffSession | None = None
    with session.begin():
        staff = (
            session.scalar(
                select(StaffUser).where(StaffUser.handle == normalized).with_for_update()
            )
            if normalized is not None
            else None
        )
        if staff is None:
            burn_verify(pin)
        elif staff.locked_until is not None and staff.locked_until > now:
            locked_until = staff.locked_until
        elif verify_pin(staff.pin_hash, pin):
            staff.failed_attempts = 0
            staff.locked_until = None
            staff.updated_at = now
            if needs_rehash(staff.pin_hash):
                staff.pin_hash = hash_pin(pin)
            issued = _open_session(session, staff.id, now)
            _audit_in_txn(
                session,
                staff_user_id=staff.id,
                action="sign_in",
                resource_type="staff_session",
                resource_id=None,
                detail=f"@{staff.handle} signed in",
            )
        else:
            staff.failed_attempts += 1
            staff.updated_at = now
            if staff.failed_attempts >= settings.pin_max_attempts:
                staff.failed_attempts = 0
                staff.locked_until = now + timedelta(minutes=settings.pin_lockout_minutes)
                locked_until = staff.locked_until

    if locked_until is not None:
        raise AccountLocked(
            f"too many wrong PINs; try again after {locked_until.isoformat(timespec='seconds')}"
        )
    if issued is None:
        raise InvalidCredentials("handle or PIN is incorrect")
    return issued


def authenticate_staff(
    session: Session, token: str | None, now: datetime | None = None
) -> StaffActor:
    if not token:
        raise NotAuthenticated("sign in first")
    now = now or datetime.now(UTC)
    row = session.execute(
        select(StaffSession, StaffUser)
        .join(StaffUser, StaffUser.id == StaffSession.staff_user_id)
        .where(
            StaffSession.token_hash == _token_hash(token),
            StaffSession.revoked_at.is_(None),
            StaffSession.expires_at > now,
        )
    ).first()
    if row is None:
        raise NotAuthenticated("session is missing, expired, or signed out")
    staff_session, staff = row
    return StaffActor(session_id=staff_session.id, staff_user_id=staff.id, handle=staff.handle)


def sign_out_staff(session: Session, token: str | None, now: datetime | None = None) -> None:
    if not token:
        return
    now = now or datetime.now(UTC)
    release_read_transaction(session)
    with session.begin():
        found = session.scalar(
            select(StaffSession)
            .where(StaffSession.token_hash == _token_hash(token), StaffSession.revoked_at.is_(None))
            .with_for_update()
        )
        if found is not None:
            found.revoked_at = now
            _audit_in_txn(
                session,
                staff_user_id=found.staff_user_id,
                action="sign_out",
                resource_type="staff_session",
                resource_id=str(found.id),
                detail="signed out",
            )


def record_audit(
    session: Session,
    actor: StaffActor,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    detail: str,
) -> None:
    release_read_transaction(session)
    with session.begin():
        _audit_in_txn(
            session,
            staff_user_id=actor.staff_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )


def lookup_customer(session: Session, handle: str) -> ConsoleUser:
    record = lookup_handle(session, handle)
    user = session.get(User, record.user_id)
    if user is None:
        raise UserNotFound(f"@{record.handle} is not registered")
    return ConsoleUser(
        user_id=user.id,
        handle=user.handle,
        phone_e164=user.phone_e164,
        wallet_account_id=record.wallet_account_id,
        created_at=user.created_at,
        balance=get_balance(session, record.wallet_account_id),
    )


def customer_by_id(session: Session, user_id: UUID) -> ConsoleUser:
    user = session.get(User, user_id)
    if user is None:
        raise UserNotFound(f"user {user_id} is not registered")
    wallet = session.scalar(select(LedgerAccount).where(LedgerAccount.owner_user_id == user.id))
    if wallet is None:
        raise UserNotFound(f"user {user_id} is not registered")
    return ConsoleUser(
        user_id=user.id,
        handle=user.handle,
        phone_e164=user.phone_e164,
        wallet_account_id=wallet.id,
        created_at=user.created_at,
        balance=get_balance(session, wallet.id),
    )


def customer_history(
    session: Session, user_id: UUID, *, limit: int, cursor: str | None
) -> HistoryPage:
    customer = customer_by_id(session, user_id)
    return wallet_history(
        session,
        user_id=customer.user_id,
        wallet_account_id=customer.wallet_account_id,
        limit=limit,
        cursor=cursor,
    )


def journal_view(session: Session, entry_id: UUID) -> JournalView:
    entry = session.get(JournalEntry, entry_id)
    if entry is None:
        raise NotFound(f"unknown journal entry {entry_id}")
    lines = list(
        session.execute(
            select(Posting, LedgerAccount)
            .join(LedgerAccount, LedgerAccount.id == Posting.account_id)
            .where(Posting.journal_entry_id == entry.id)
            .order_by(Posting.line_no)
        )
    )
    return JournalView(entry, [(posting, account) for posting, account in lines])


def latest_recon(session: Session) -> LatestRecon:
    run = session.scalar(select(ReconRun).order_by(ReconRun.started_at.desc(), ReconRun.id.desc()))
    if run is None:
        return LatestRecon(None, [])
    breaks = list(
        session.scalars(
            select(ReconBreak)
            .where(ReconBreak.run_id == run.id)
            .order_by(ReconBreak.kind, ReconBreak.id)
        )
    )
    return LatestRecon(run, breaks)


def list_suspense(session: Session, *, limit: int = 50) -> list[SuspenseItem]:
    return list(
        session.scalars(
            select(SuspenseItem)
            .order_by(SuspenseItem.status, SuspenseItem.created_at.desc(), SuspenseItem.id)
            .limit(limit)
        )
    )


def list_dlq(session: Session, *, limit: int = 50) -> list[OutboxJob]:
    return list_dead_jobs(session, limit=limit)


def replay_dlq(session: Session, actor: StaffActor, job_id: UUID) -> None:
    try:
        replay_dead_job(session, job_id)
    except OutboxError as exc:
        message = str(exc)
        if "no such" in message:
            raise OutboxJobNotFound(message) from exc
        raise InvalidOutbox(message) from exc
    record_audit(
        session,
        actor,
        action="replay_dlq",
        resource_type="outbox_job",
        resource_id=str(job_id),
        detail="replayed a dead outbox job",
    )


def list_audit(session: Session, *, limit: int = 50) -> list[tuple[StaffAuditEvent, str]]:
    return list(
        session.execute(
            select(StaffAuditEvent, StaffUser.handle)
            .join(StaffUser, StaffUser.id == StaffAuditEvent.staff_user_id)
            .order_by(StaffAuditEvent.created_at.desc(), StaffAuditEvent.id.desc())
            .limit(limit)
        )
    )


def _staff_handle(raw: str | None) -> str:
    if not isinstance(raw, str):
        raise InvalidHandle("handle must be a string")
    handle = raw.strip()
    if handle.startswith("@"):
        handle = handle[1:]
    handle = handle.lower()
    if HANDLE_RE.fullmatch(handle) is None:
        raise InvalidHandle(
            "handle must be 3-20 characters, start with a letter, "
            "and use only letters, digits, and underscores"
        )
    return handle


def _open_session(session: Session, staff_user_id: UUID, now: datetime) -> IssuedStaffSession:
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=get_settings().session_ttl_minutes)
    session.add(
        StaffSession(
            id=uuid4(),
            staff_user_id=staff_user_id,
            token_hash=_token_hash(token),
            expires_at=expires_at,
        )
    )
    return IssuedStaffSession(token=token, staff_user_id=staff_user_id, expires_at=expires_at)


def _audit_in_txn(
    session: Session,
    *,
    staff_user_id: UUID,
    action: str,
    resource_type: str,
    resource_id: str | None,
    detail: str,
) -> None:
    session.add(
        StaffAuditEvent(
            id=uuid4(),
            staff_user_id=staff_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail[:500],
        )
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
