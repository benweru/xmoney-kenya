"""Operator CLI for suspense. Not an HTTP route; the public demo cannot mint this way."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from xmoney.db import get_sessionmaker, import_mapped_tables
from xmoney.suspense.models import SuspenseItem
from xmoney.suspense.service import apply_to_wallet, open_suspense, refund_to_float

logger = logging.getLogger("xmoney.suspense")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="xmoney-suspense", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    open_cmd = commands.add_parser("open", help="park unmatched value in system:suspense")
    open_cmd.add_argument("--cents", type=int, required=True)
    open_cmd.add_argument("--reason", required=True)
    open_cmd.add_argument("--break", dest="break_id", default=None)

    apply_cmd = commands.add_parser("apply", help="credit a wallet and close the item")
    apply_cmd.add_argument("--id", dest="item_id", required=True)
    apply_cmd.add_argument("--to", dest="handle", required=True)
    apply_cmd.add_argument("--reason", required=True)

    refund_cmd = commands.add_parser("refund", help="return the value to the M-PESA float")
    refund_cmd.add_argument("--id", dest="item_id", required=True)
    refund_cmd.add_argument("--reason", required=True)

    commands.add_parser("list", help="show open items")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    import_mapped_tables()
    with get_sessionmaker()() as session:
        if args.command == "open":
            break_id = UUID(args.break_id) if args.break_id else None
            view = open_suspense(
                session, amount_cents=args.cents, reason=args.reason, recon_break_id=break_id
            )
            logger.info("opened %s for %d cents (%s)", view.id, view.amount_cents, view.status)
            return
        if args.command == "apply":
            view = apply_to_wallet(
                session, item_id=UUID(args.item_id), handle=args.handle, reason=args.reason
            )
            logger.info("applied %s (%s)", view.id, view.status)
            return
        if args.command == "refund":
            view = refund_to_float(session, item_id=UUID(args.item_id), reason=args.reason)
            logger.info("refunded %s (%s)", view.id, view.status)
            return
        rows = session.scalars(
            select(SuspenseItem)
            .where(SuspenseItem.status == "open")
            .order_by(SuspenseItem.created_at)
        ).all()
        if not rows:
            logger.info("no open suspense items")
            return
        for row in rows:
            logger.info("%s  %d cents  %s", row.id, row.amount_cents, row.open_reason)


if __name__ == "__main__":
    main()
