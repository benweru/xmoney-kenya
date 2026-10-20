"""Versioned P2P fee schedules. The transfer stores the version it used.

The default schedule is a demo tariff, not a Safaricom or CBK figure:
KES 100 and under is free, KES 1,000 and under is a flat KES 1, and above
that is KES 2 plus 0.50%. A later version can add a free monthly allowance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xmoney.db import release_read_transaction
from xmoney.errors import InvalidTransfer, LedgerError
from xmoney.ledger.money import require_cents
from xmoney.transfers.models import PRODUCT_P2P, FeeSchedule, Transfer

BPS_DENOMINATOR = 10_000
DEFAULT_P2P_SCHEDULE_ID = UUID("00000000-0000-4000-8000-0000000000f1")
DEFAULT_P2P_BANDS: tuple[dict[str, int | None], ...] = (
    {"up_to_cents": 10_000, "flat_cents": 0, "rate_bps": 0},
    {"up_to_cents": 100_000, "flat_cents": 100, "rate_bps": 0},
    {"up_to_cents": None, "flat_cents": 200, "rate_bps": 50},
)


@dataclass(frozen=True)
class Band:
    up_to_cents: int | None
    flat_cents: int
    rate_bps: int


@dataclass(frozen=True)
class FeeQuote:
    amount_cents: int
    fee_cents: int
    total_cents: int
    schedule_id: UUID
    schedule_version: int
    waived: bool


def round_half_up(numerator: int, denominator: int) -> int:
    """Integer division that rounds .5 away from zero for non-negative values."""
    if denominator <= 0 or numerator < 0:
        raise InvalidTransfer("fee rounding inputs must be non-negative")
    return (numerator + denominator // 2) // denominator


def parse_bands(raw: object) -> tuple[Band, ...]:
    if not isinstance(raw, list) or not raw:
        raise InvalidTransfer("fee schedule bands must be a non-empty list")
    bands: list[Band] = []
    previous_cap: int | None = 0
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise InvalidTransfer("each fee band must be an object")
        cap = item.get("up_to_cents")
        flat = item.get("flat_cents")
        rate = item.get("rate_bps")
        last = index == len(raw) - 1
        if last:
            if cap is not None:
                raise InvalidTransfer("the last fee band must be unbounded")
        elif not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
            raise InvalidTransfer("fee band up_to_cents must be a positive integer")
        elif previous_cap is not None and cap <= previous_cap:
            raise InvalidTransfer("fee bands must rise by up_to_cents")
        if not isinstance(flat, int) or isinstance(flat, bool) or flat < 0:
            raise InvalidTransfer("fee band flat_cents must be a non-negative integer")
        if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
            raise InvalidTransfer("fee band rate_bps must be a non-negative integer")
        bands.append(Band(None if last else cap, flat, rate))
        previous_cap = None if last else cap
    return tuple(bands)


def fee_for_amount(bands: tuple[Band, ...], amount_cents: int) -> int:
    amount = require_cents(amount_cents)
    for band in bands:
        if band.up_to_cents is None or amount <= band.up_to_cents:
            variable = round_half_up(amount * band.rate_bps, BPS_DENOMINATOR)
            return band.flat_cents + variable
    raise InvalidTransfer("amount is not covered by the fee schedule")


def ensure_default_p2p_schedule(session: Session) -> None:
    """Insert version 1 if the table was truncated (demo reset)."""
    existing = session.scalar(select(FeeSchedule.id).where(FeeSchedule.product == PRODUCT_P2P))
    if existing is not None:
        return
    session.add(
        FeeSchedule(
            id=DEFAULT_P2P_SCHEDULE_ID,
            version=1,
            product=PRODUCT_P2P,
            free_count_per_calendar_month=0,
            bands=list(DEFAULT_P2P_BANDS),
        )
    )


def publish_p2p_schedule(
    session: Session,
    *,
    bands: list[dict[str, Any]],
    free_count_per_calendar_month: int = 0,
    effective_from: datetime | None = None,
) -> FeeSchedule:
    """Append a new P2P version. Existing transfers keep the version they used."""
    parse_bands(bands)
    if free_count_per_calendar_month < 0:
        raise InvalidTransfer("free_count_per_calendar_month cannot be negative")
    release_read_transaction(session)
    with session.begin():
        next_version = (
            session.scalar(select(func.coalesce(func.max(FeeSchedule.version), 0))) or 0
        ) + 1
        row = FeeSchedule(
            id=uuid4(),
            version=next_version,
            product=PRODUCT_P2P,
            free_count_per_calendar_month=free_count_per_calendar_month,
            bands=bands,
            effective_from=effective_from or datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        return row


def quote_p2p(session: Session, *, sender_user_id: UUID, amount_cents: int) -> FeeQuote:
    amount = require_cents(amount_cents)
    schedule = current_p2p_schedule(session)
    used = _sends_this_utc_month(session, sender_user_id)
    waived = used < schedule.free_count_per_calendar_month
    fee = 0 if waived else fee_for_amount(parse_bands(schedule.bands), amount)
    return FeeQuote(
        amount_cents=amount,
        fee_cents=fee,
        total_cents=amount + fee,
        schedule_id=schedule.id,
        schedule_version=schedule.version,
        waived=waived,
    )


def current_p2p_schedule(session: Session) -> FeeSchedule:
    now = datetime.now(UTC)
    row = session.scalar(
        select(FeeSchedule)
        .where(FeeSchedule.product == PRODUCT_P2P, FeeSchedule.effective_from <= now)
        .order_by(FeeSchedule.version.desc())
        .limit(1)
    )
    if row is None:
        raise LedgerError("no P2P fee schedule is in force")
    return row


def _sends_this_utc_month(session: Session, sender_user_id: UUID) -> int:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    counted = session.scalar(
        select(func.count())
        .select_from(Transfer)
        .where(Transfer.sender_user_id == sender_user_id, Transfer.created_at >= month_start)
    )
    return int(counted or 0)
