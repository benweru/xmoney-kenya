"""Unmatched value parks in suspense, then goes to a wallet or back to the float."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from xmoney.errors import InvalidSuspense
from xmoney.identity.service import register_user
from xmoney.ledger.service import get_balance, trial_totals
from xmoney.ledger.system import MPESA_FLOAT, SUSPENSE
from xmoney.recon.models import ReconBreak
from xmoney.suspense.service import apply_to_wallet, open_suspense, refund_to_float


def test_apply_credits_the_named_wallet(db: Session) -> None:
    amina = register_user(db, handle="amina", phone="+254712345678")
    opened = open_suspense(db, amount_cents=1_500, reason="unmatched STK receipt")
    assert opened.status == "open"
    assert get_balance(db, SUSPENSE.id).balance_cents == 1_500
    assert get_balance(db, MPESA_FLOAT.id).balance_cents == 1_500

    applied = apply_to_wallet(db, item_id=opened.id, handle="amina", reason="customer called")
    assert applied.status == "applied"
    assert get_balance(db, SUSPENSE.id).balance_cents == 0
    assert get_balance(db, amina.wallet_account_id).balance_cents == 1_500
    assert get_balance(db, MPESA_FLOAT.id).balance_cents == 1_500
    debits, credits = trial_totals(db)
    assert debits == credits


def test_refund_returns_value_to_the_float(db: Session) -> None:
    open_suspense(db, amount_cents=800, reason="duplicate collection")
    register_user(db, handle="amina", phone="+254712345678")
    opened = open_suspense(db, amount_cents=200, reason="second unmatched")
    refund_to_float(db, item_id=opened.id, reason="return to Safaricom sandbox")
    assert get_balance(db, SUSPENSE.id).balance_cents == 800
    assert get_balance(db, MPESA_FLOAT.id).balance_cents == 800


def test_a_closed_item_cannot_be_applied_again(db: Session) -> None:
    register_user(db, handle="amina", phone="+254712345678")
    opened = open_suspense(db, amount_cents=100, reason="once")
    apply_to_wallet(db, item_id=opened.id, handle="amina", reason="done")
    with pytest.raises(InvalidSuspense, match="applied"):
        apply_to_wallet(db, item_id=opened.id, handle="amina", reason="again")


def test_one_open_item_per_break(db: Session) -> None:
    from xmoney.payments.models import CallbackDisposition, StkCallbackLog
    from xmoney.recon.service import run_recon

    with db.begin():
        db.add(
            StkCallbackLog(
                id=uuid4(),
                checkout_request_id="ws_CO_UNKNOWN",
                topup_id=None,
                result_code=0,
                disposition=CallbackDisposition.UNMATCHED.value,
                payload={},
            )
        )
    report = run_recon(db)
    break_id = db.scalar(select(ReconBreak.id).where(ReconBreak.run_id == report.run_id))
    assert break_id is not None
    open_suspense(db, amount_cents=100, reason="from recon", recon_break_id=break_id)
    with pytest.raises(InvalidSuspense, match="already has an open"):
        open_suspense(db, amount_cents=100, reason="again", recon_break_id=break_id)
