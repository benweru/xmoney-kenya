"""Handle and Kenyan mobile number rules."""

from __future__ import annotations

import re

from xmoney.errors import InvalidHandle, InvalidPhone

HANDLE_RE = re.compile(r"^[a-z][a-z0-9_]{2,19}$")
PHONE_RE = re.compile(r"^\+254[17]\d{8}$")

RESERVED_HANDLES = frozenset(
    {
        "admin",
        "administrator",
        "clearing",
        "fees",
        "float",
        "help",
        "mpesa",
        "null",
        "root",
        "safaricom",
        "support",
        "suspense",
        "system",
        "void",
        "xmoney",
    }
)


def normalize_handle(raw: str) -> str:
    if not isinstance(raw, str):
        raise InvalidHandle("handle must be a string")
    handle = raw.strip()
    if handle.startswith("@"):
        handle = handle[1:]
    handle = handle.lower()
    if handle in RESERVED_HANDLES or HANDLE_RE.fullmatch(handle) is None:
        raise InvalidHandle(
            "handle must be 3-20 characters, start with a letter, "
            "and use only letters, digits, and underscores"
        )
    return handle


def normalize_phone(raw: str) -> str:
    """Accept E.164 only. Spaces and dashes are ignored; a leading 0 is not."""
    if not isinstance(raw, str):
        raise InvalidPhone("phone must be a string")
    phone = raw.strip().replace(" ", "").replace("-", "")
    if PHONE_RE.fullmatch(phone) is None:
        raise InvalidPhone(
            "phone must be E.164 Kenya mobile format: +254 followed by 7 or 1 and eight digits"
        )
    return phone
