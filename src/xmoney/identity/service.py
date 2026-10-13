"""Register a person and open their wallet in the same transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xmoney.db import release_read_transaction
from xmoney.errors import AccountNotFound, HandleTaken, PhoneTaken, UserNotFound
from xmoney.identity.models import User
from xmoney.identity.validators import normalize_handle, normalize_phone
from xmoney.ledger.models import AccountType, LedgerAccount, NormalSide
from xmoney.ledger.system import wallet_code


@dataclass(frozen=True)
class RegisteredUser:
    id: UUID
    handle: str
    phone_e164: str
    wallet_account_id: UUID
    created_at: datetime


@dataclass(frozen=True)
class HandleRecord:
    user_id: UUID
    handle: str
    wallet_account_id: UUID


def register_user(session: Session, *, handle: str, phone: str) -> RegisteredUser:
    """Create the user and a credit-normal KES wallet. Commits the session."""
    normalized_handle = normalize_handle(handle)
    normalized_phone = normalize_phone(phone)
    release_read_transaction(session)
    user_id = uuid4()
    wallet_id = uuid4()
    try:
        with session.begin():
            user = User(id=user_id, handle=normalized_handle, phone_e164=normalized_phone)
            session.add(user)
            session.add(
                LedgerAccount(
                    id=wallet_id,
                    code=wallet_code(user_id),
                    name=f"Wallet @{normalized_handle}",
                    account_type=AccountType.LIABILITY.value,
                    normal_side=NormalSide.CREDIT.value,
                    currency="KES",
                    owner_user_id=user_id,
                )
            )
            session.flush()
            session.refresh(user)
            created_at = user.created_at
    except IntegrityError as exc:
        name = _constraint_name(exc)
        if name == "uq_users_handle":
            raise HandleTaken(f"@{normalized_handle} is already registered") from exc
        if name == "uq_users_phone_e164":
            raise PhoneTaken("that phone number is already registered") from exc
        raise
    return RegisteredUser(
        id=user_id,
        handle=normalized_handle,
        phone_e164=normalized_phone,
        wallet_account_id=wallet_id,
        created_at=created_at,
    )


def lookup_handle(session: Session, handle: str) -> HandleRecord:
    """Resolve a handle to its wallet. The phone number is not part of the result."""
    normalized = normalize_handle(handle)
    user = session.scalar(select(User).where(User.handle == normalized))
    if user is None:
        raise UserNotFound(f"@{normalized} is not registered")
    wallet = session.scalar(select(LedgerAccount).where(LedgerAccount.owner_user_id == user.id))
    if wallet is None:
        raise AccountNotFound(f"wallet for @{normalized} is missing")
    return HandleRecord(user_id=user.id, handle=user.handle, wallet_account_id=wallet.id)


def _constraint_name(exc: IntegrityError) -> str:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None) if diag is not None else None
    if name:
        return str(name)
    message = str(exc)
    for candidate in ("uq_users_handle", "uq_users_phone_e164"):
        if candidate in message:
            return candidate
    return ""
