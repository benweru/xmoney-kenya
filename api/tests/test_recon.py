"""The reconciler classifies breaks and does not repair them."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from xmoney.demo import seed
from xmoney.identity.service import register_user
from xmoney.payments.daraja import parse_stk_callback
from xmoney.payments.deps import Rails
from xmoney.payments.models import CallbackDisposition, StkCallbackLog
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
from xmoney.recon.models import BreakKind
from xmoney.recon.service import run_recon


class _QueryDisagrees:
    name = "mock"
    queries = 0

    def obtain_token(self) -> AccessToken:
        return AccessToken(token="t", expires_in=3599)

    def stk_push(self, request: StkPushRequest) -> StkPushAccepted:
        raise RuntimeError("recon test does not push")

    def stk_query(self, checkout_request_id: str) -> StkQueryResult:
        self.queries += 1
        return StkQueryResult(checkout_request_id, False, 1032, "cancelled", None)

    def parse_stk_callback(self, payload: object) -> StkCallback:
        return parse_stk_callback(payload)

    def b2c_payment(self, request: B2cPaymentRequest) -> B2cAccepted:
        raise RuntimeError("recon test does not pay out")

    def parse_b2c_result(self, payload: object) -> B2cResult:
        raise RuntimeError("recon test does not pay out")


def test_a_clean_seed_has_no_breaks(db: Session) -> None:
    seed(db)
    report = run_recon(db)
    assert report.break_count == 0
    assert report.unexplained_count == 0
    assert report.kinds == ()


def test_running_balance_drift_is_classified(db: Session) -> None:
    user = register_user(db, handle="amina", phone="+254712345678")
    db.rollback()
    with db.begin():
        db.execute(text("SELECT set_config('xmoney.maintain_running_balance', 'on', true)"))
        db.execute(
            text(
                "UPDATE ledger_accounts SET running_credit_cents = running_credit_cents + 7 "
                "WHERE id = :id"
            ),
            {"id": user.wallet_account_id},
        )
    report = run_recon(db)
    assert report.kinds == (BreakKind.RUNNING_BALANCE_DRIFT.value,)
    assert report.unexplained_count == 0


def test_unmatched_and_wrong_amount_callbacks_are_classified(db: Session) -> None:
    db.rollback()
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
        db.add(
            StkCallbackLog(
                id=uuid4(),
                checkout_request_id="ws_CO_WRONGAMT",
                topup_id=None,
                result_code=0,
                disposition=CallbackDisposition.AMOUNT_MISMATCH.value,
                payload={},
            )
        )
    report = run_recon(db)
    assert sorted(report.kinds) == [
        BreakKind.AMOUNT_MISMATCH.value,
        BreakKind.MISSING_ON_LEDGER.value,
    ]


def test_stk_query_that_disagrees_is_missing_on_the_rail(db: Session) -> None:
    seed(db)
    rail = _QueryDisagrees()
    report = run_recon(db, Rails.of(rail))
    assert report.kinds.count(BreakKind.MISSING_ON_RAIL.value) == 4
    assert rail.queries == 4
