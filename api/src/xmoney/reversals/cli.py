"""Operator CLI for reversals. HTTP writes are staff-only and off on a public demo."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from xmoney.db import get_sessionmaker, import_mapped_tables
from xmoney.reversals.models import Reversal, ReversalStatus
from xmoney.reversals.service import approve_reversal, propose_reversal, reject_reversal

logger = logging.getLogger("xmoney.reversals")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="xmoney-reversal", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    propose = commands.add_parser("propose", help="reverse a journal entry")
    propose.add_argument("--entry", required=True)
    propose.add_argument("--reason", required=True)
    propose.add_argument("--maker", required=True)

    approve = commands.add_parser("approve", help="second actor posts a large reversal")
    approve.add_argument("--id", dest="item_id", required=True)
    approve.add_argument("--checker", required=True)

    reject = commands.add_parser("reject", help="second actor refuses a proposed reversal")
    reject.add_argument("--id", dest="item_id", required=True)
    reject.add_argument("--checker", required=True)
    reject.add_argument("--reason", required=True)

    commands.add_parser("list", help="show proposed reversals")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    import_mapped_tables()
    with get_sessionmaker()() as session:
        if args.command == "propose":
            view = propose_reversal(
                session,
                original_journal_entry_id=UUID(args.entry),
                reason=args.reason,
                maker=args.maker,
            )
            logger.info(
                "%s %s (%d cents)%s",
                view.status,
                view.id,
                view.amount_cents,
                " — needs checker" if view.needs_checker else "",
            )
            return
        if args.command == "approve":
            view = approve_reversal(session, reversal_id=UUID(args.item_id), checker=args.checker)
            logger.info("posted %s", view.id)
            return
        if args.command == "reject":
            view = reject_reversal(
                session,
                reversal_id=UUID(args.item_id),
                checker=args.checker,
                reason=args.reason,
            )
            logger.info("rejected %s", view.id)
            return
        rows = session.scalars(
            select(Reversal)
            .where(Reversal.status == ReversalStatus.PROPOSED.value)
            .order_by(Reversal.created_at)
        ).all()
        if not rows:
            logger.info("no proposed reversals")
            return
        for row in rows:
            logger.info(
                "%s  %d cents  maker=%s  entry=%s  %s",
                row.id,
                row.amount_cents,
                row.maker,
                row.original_journal_entry_id,
                row.reason,
            )


if __name__ == "__main__":
    main()
