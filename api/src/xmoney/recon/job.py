"""Run one reconciliation pass. EventBridge starts this as an ECS task."""

from __future__ import annotations

import logging

from xmoney.db import get_sessionmaker, import_mapped_tables
from xmoney.payments.deps import build_rails
from xmoney.recon.service import run_recon

logger = logging.getLogger("xmoney.recon")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    import_mapped_tables()
    rails = build_rails()
    try:
        with get_sessionmaker()() as session:
            report = run_recon(session, rails)
    finally:
        rails.close()
    logger.info(
        "recon %s: %d classified break(s), %d unexplained",
        report.run_id,
        report.break_count,
        report.unexplained_count,
    )


if __name__ == "__main__":
    main()
