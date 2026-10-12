"""Integer KES cents. Floats never enter the ledger."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from xmoney.errors import InvalidAmount, InvalidIdempotencyKey, InvalidJournal, UnbalancedEntry

MAX_CENTS = 10**15
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9:_\-./]{1,200}$")


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


@dataclass(frozen=True)
class PostingLine:
    account_id: UUID
    direction: Direction
    amount_cents: int


@dataclass(frozen=True)
class PostCommand:
    idempotency_key: str
    description: str
    postings: tuple[PostingLine, ...]
    external_ref: str | None = None


@dataclass(frozen=True)
class PostResult:
    entry_id: UUID
    idempotency_key: str
    request_hash: str
    created: bool


def require_cents(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidAmount("amounts must be integer KES cents; floats are rejected")
    if value <= 0 or value > MAX_CENTS:
        raise InvalidAmount("amount_cents must be a positive integer within range")
    return value


def require_idempotency_key(value: str) -> str:
    key = value.strip()
    if _IDEMPOTENCY_RE.fullmatch(key) is None:
        raise InvalidIdempotencyKey(
            "idempotency_key must be 1-200 characters from [A-Za-z0-9:_.-/]"
        )
    return key


def request_hash(command: PostCommand) -> str:
    """Hash the economic content of an entry, ignoring posting order."""
    postings = [
        {
            "account_id": str(line.account_id),
            "amount_cents": line.amount_cents,
            "direction": line.direction.value,
        }
        for line in sorted(
            command.postings,
            key=lambda line: (str(line.account_id), line.direction.value, line.amount_cents),
        )
    ]
    payload = {
        "description": command.description,
        "external_ref": command.external_ref,
        "postings": postings,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_command(command: PostCommand) -> PostCommand:
    key = require_idempotency_key(command.idempotency_key)
    description = command.description.strip()
    if not description or len(description) > 500:
        raise InvalidJournal("description must be 1-500 characters")
    external = command.external_ref
    if external is not None:
        external = external.strip()
        if not external or len(external) > 120:
            raise InvalidJournal("external_ref must be 1-120 characters when provided")
    if len(command.postings) < 2:
        raise UnbalancedEntry("a journal entry needs at least two postings")
    if len(command.postings) > 32:
        raise InvalidJournal("a journal entry cannot exceed 32 postings")

    lines: list[PostingLine] = []
    debit = 0
    credit = 0
    for line in command.postings:
        amount = require_cents(line.amount_cents)
        if isinstance(line.direction, Direction):
            direction = line.direction
        else:
            try:
                direction = Direction(line.direction)
            except ValueError as exc:
                raise InvalidJournal("direction must be debit or credit") from exc
        if not isinstance(line.account_id, UUID):
            raise InvalidJournal("account_id must be a UUID")
        lines.append(
            PostingLine(account_id=line.account_id, direction=direction, amount_cents=amount)
        )
        if direction is Direction.DEBIT:
            debit += amount
        else:
            credit += amount
    if debit != credit:
        raise UnbalancedEntry(f"debits ({debit}) do not equal credits ({credit})")
    return PostCommand(
        idempotency_key=key,
        description=description,
        postings=tuple(lines),
        external_ref=external,
    )
