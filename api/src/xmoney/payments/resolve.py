"""Resolve top-ups still waiting on M-PESA. Run it on a schedule until the M3 worker owns it."""

from __future__ import annotations

import logging

from xmoney.db import get_sessionmaker
from xmoney.payments.deps import build_provider
from xmoney.payments.topups import resolve_stale_topups


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    provider = build_provider()
    try:
        with get_sessionmaker()() as session:
            changed = resolve_stale_topups(session, provider)
    finally:
        provider.close()
    logging.getLogger("xmoney.topups").info("resolved %d top-up(s)", changed)


if __name__ == "__main__":
    main()
