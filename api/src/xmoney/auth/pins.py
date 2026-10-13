"""PIN shape rules and Argon2id hashing."""

from __future__ import annotations

import re
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from xmoney.errors import InvalidPin

_PIN_RE = re.compile(r"^[0-9]{4,6}$")
_DIGITS = "0123456789"

_hasher = PasswordHasher()


def require_new_pin(raw: object) -> str:
    """Validate a PIN being set. Repeated digits and straight runs are refused."""
    if not isinstance(raw, str) or _PIN_RE.fullmatch(raw) is None:
        raise InvalidPin("PIN must be 4-6 digits")
    if len(set(raw)) == 1 or raw in _DIGITS or raw in _DIGITS[::-1]:
        raise InvalidPin("PIN is too easy to guess; avoid repeated digits and runs like 1234")
    return raw


def hash_pin(pin: str) -> str:
    return _hasher.hash(pin)


def verify_pin(pin_hash: str, pin: object) -> bool:
    if not isinstance(pin, str) or _PIN_RE.fullmatch(pin) is None:
        return False
    try:
        return _hasher.verify(pin_hash, pin)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(pin_hash: str) -> bool:
    return _hasher.check_needs_rehash(pin_hash)


def burn_verify(pin: object) -> None:
    """Spend the same Argon2 time as a real check, so unknown phones are not faster."""
    verify_pin(_dummy_hash(), pin)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("pin-for-unknown-phones")
