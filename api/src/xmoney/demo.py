"""Seed the public demo, and wipe it back to that seed every night.

`xmoney-demo seed` adds three wallets with some history, unless they exist.
`xmoney-demo reset --yes` empties every table except the Alembic version,
recreates the system accounts, and seeds again. EventBridge Scheduler runs the
reset at 03:00 Nairobi time on AWS.

Seed top-ups go through the real top-up code with a rail that approves at
once, seed sends go through the real transfer code, and one seed cash-out
goes through the real B2C hold, so the history a visitor sees is the same
shape as their own. Seed wallets have no PIN unless DEMO_SEED_PIN is set, so
nobody can sign in as them on the public demo.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import count

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from xmoney.auth import models as auth_models  # noqa: F401
from xmoney.db import Base, get_sessionmaker
from xmoney.identity import models as identity_models
from xmoney.identity.service import RegisteredUser, register_user
from xmoney.inbox import models as inbox_models  # noqa: F401
from xmoney.ledger import models as ledger_models  # noqa: F401
from xmoney.ledger.service import seed_system_accounts
from xmoney.payments import models as payments_models  # noqa: F401
from xmoney.payments.cashouts import handle_b2c_callback, start_cashout
from xmoney.payments.daraja import parse_b2c_result, parse_stk_callback
from xmoney.payments.jobs import send_due
from xmoney.payments.models import Cashout, Topup
from xmoney.payments.provider import (
    AccessToken,
    B2cAccepted,
    B2cPaymentRequest,
    B2cResult,
    StkCallback,
    StkPushAccepted,
    StkPushRequest,
    StkQueryResult,
)
from xmoney.payments.topups import handle_stk_callback, start_topup
from xmoney.ratelimit import models as ratelimit_models  # noqa: F401
from xmoney.transfers import models as transfers_models  # noqa: F401
from xmoney.transfers.fees import ensure_default_p2p_schedule
from xmoney.transfers.service import send

logger = logging.getLogger("xmoney.demo")


@dataclass(frozen=True)
class DemoUser:
    handle: str
    phone: str
    topups_kes: tuple[int, ...]


DEMO_USERS = (
    DemoUser("amina", "+254712345000", (5_000,)),
    DemoUser("baraka", "+254733111000", (2_000, 1_500)),
    DemoUser("wanjiku", "+254701222000", (3_000,)),
)

# (from, to, KES, note), in order.
DEMO_SENDS = (
    ("amina", "baraka", 450, "Lunch at Java"),
    ("baraka", "wanjiku", 1_200, "Matatu fare, Thika road trip"),
    ("wanjiku", "amina", 300, "Chai"),
    ("amina", "wanjiku", 2_000, "Chama contribution"),
)


class SeedRail:
    """Accepts every push. The caller then delivers a success callback for it."""

    name = "mock"

    def __init__(self) -> None:
        self._ids = count(1)

    def obtain_token(self) -> AccessToken:
        return AccessToken(token="seed", expires_in=3599)

    def stk_push(self, request: StkPushRequest) -> StkPushAccepted:
        n = next(self._ids)
        return StkPushAccepted(
            merchant_request_id=f"seed-{n}",
            checkout_request_id=f"ws_CO_SEED{n:06d}",
            response_code="0",
            response_description="Success. Request accepted for processing",
            customer_message="Success. Request accepted for processing",
        )

    def stk_query(self, checkout_request_id: str) -> StkQueryResult:
        return StkQueryResult(checkout_request_id, False, 0, "seeded", None)

    def parse_stk_callback(self, payload: object) -> StkCallback:
        return parse_stk_callback(payload)

    def b2c_payment(self, request: B2cPaymentRequest) -> B2cAccepted:
        n = next(self._ids)
        return B2cAccepted(
            conversation_id=f"AG_SEED{n:06d}",
            originator_conversation_id=request.originator_conversation_id,
            response_code="0",
            response_description="Accept the service request successfully.",
        )

    def parse_b2c_result(self, payload: object) -> B2cResult:
        return parse_b2c_result(payload)


def seed(session: Session) -> bool:
    """Add the demo wallets and their history. Returns False if they are already there."""
    first = DEMO_USERS[0].handle
    if session.scalar(select(identity_models.User.id).where(identity_models.User.handle == first)):
        return False
    session.rollback()
    pin = os.environ.get("DEMO_SEED_PIN") or None
    rail = SeedRail()
    users: dict[str, RegisteredUser] = {}
    for demo in DEMO_USERS:
        user = register_user(session, handle=demo.handle, phone=demo.phone, pin=pin)
        users[demo.handle] = user
        for i, kes in enumerate(demo.topups_kes, start=1):
            _seed_topup(session, rail, user, kes, key=f"seed:{demo.handle}:{i}")
    for i, (sender, recipient, kes, note) in enumerate(DEMO_SENDS, start=1):
        payer = users[sender]
        send(
            session,
            sender_user_id=payer.id,
            sender_handle=payer.handle,
            sender_wallet_id=payer.wallet_account_id,
            to_handle=recipient,
            amount_cents=kes * 100,
            idempotency_key=f"seed:send:{i}",
            note=note,
        )
    _seed_cashout(session, rail, users["amina"], 500, key="seed:cashout:amina")
    return True


def reset(session: Session) -> None:
    """Empty every application table, then recreate the system accounts and the seed."""
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    session.rollback()
    with session.begin():
        # The ledger seal (migration 0002) refuses TRUNCATE unless this is set for the transaction.
        session.execute(text("SET LOCAL xmoney.allow_truncate = 'on'"))
        session.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        seed_system_accounts(session)
        ensure_default_p2p_schedule(session)
    seed(session)


def _seed_topup(
    session: Session, rail: SeedRail, user: RegisteredUser, kes: int, *, key: str
) -> None:
    view = start_topup(
        session,
        rail,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=kes * 100,
        idempotency_key=key,
    )
    send_due(session, rail)
    seeded = session.get(Topup, view.id, populate_existing=True)
    assert seeded is not None and seeded.checkout_request_id is not None
    receipt = "SBOXSEED" + seeded.checkout_request_id[-4:]
    handle_stk_callback(
        session,
        rail,
        {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "seed",
                    "CheckoutRequestID": seeded.checkout_request_id,
                    "ResultCode": 0,
                    "ResultDesc": "The service request is processed successfully.",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": kes},
                            {"Name": "MpesaReceiptNumber", "Value": receipt},
                            {"Name": "PhoneNumber", "Value": int(user.phone_e164[1:])},
                        ]
                    },
                }
            }
        },
    )


def _seed_cashout(
    session: Session, rail: SeedRail, user: RegisteredUser, kes: int, *, key: str
) -> None:
    view = start_cashout(
        session,
        rail,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=kes * 100,
        idempotency_key=key,
    )
    send_due(session, rail)
    seeded = session.get(Cashout, view.id, populate_existing=True)
    assert seeded is not None
    receipt = "SBOXCASH" + seeded.originator_conversation_id[-4:]
    handle_b2c_callback(
        session,
        rail,
        {
            "Result": {
                "ResultType": 0,
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "OriginatorConversationID": seeded.originator_conversation_id,
                "ConversationID": seeded.conversation_id,
                "TransactionID": receipt,
                "ResultParameters": {
                    "ResultParameter": [
                        {"Key": "TransactionAmount", "Value": kes},
                        {"Key": "TransactionReceipt", "Value": receipt},
                    ]
                },
            }
        },
        timed_out=False,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="xmoney-demo", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="add the demo wallets unless they exist")
    wipe = commands.add_parser("reset", help="delete every wallet and payment, then seed")
    wipe.add_argument("--yes", action="store_true", help="confirm deleting all data")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    with get_sessionmaker()() as session:
        if args.command == "seed":
            added = seed(session)
            logger.info("seeded the demo" if added else "demo wallets already exist")
            return
        if not args.yes:
            parser.error("reset deletes every wallet and payment; pass --yes to confirm")
        reset(session)
        logger.info("reset the demo to its seed")


if __name__ == "__main__":
    main()
