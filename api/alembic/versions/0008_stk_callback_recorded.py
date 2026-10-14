"""Allow stk_callbacks.disposition = recorded (success seen, not yet credited).

Revision ID: 0008_stk_callback_recorded
Revises: 0007_rate_limits
Create Date: 2026-10-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_stk_callback_recorded"
down_revision: str | None = "0007_rate_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_stk_callbacks_disposition", "stk_callbacks", type_="check")
    op.create_check_constraint(
        "ck_stk_callbacks_disposition",
        "stk_callbacks",
        "disposition IN ("
        "'applied', 'duplicate', 'conflict', 'amount_mismatch', 'unmatched', 'recorded')",
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM stk_callbacks WHERE disposition = 'recorded'"))
    op.drop_constraint("ck_stk_callbacks_disposition", "stk_callbacks", type_="check")
    op.create_check_constraint(
        "ck_stk_callbacks_disposition",
        "stk_callbacks",
        "disposition IN ('applied', 'duplicate', 'conflict', 'amount_mismatch', 'unmatched')",
    )
