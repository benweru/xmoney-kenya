"""The reconciler classifies breaks and does not repair them."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from xmoney.demo import seed
from xmoney.identity.service import register_user
from xmoney.payments.daraja import parse_stk_callback
from xmoney.payments.deps import Rails
from xmoney.payments.models import CallbackDisposition, StkCallbackLog, Topup, TopupStatus
from xmoney.payments.provider import (
    AccessToken,
    B2cAccepted,
    B2cPaymentRequest,
    B2cResult,
    Outcome,
    SettlementRow,
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


def test_closing_suspense_quiets_the_next_recon_run(db: Session) -> None:
    from sqlalchemy import select

    from xmoney.recon.models import ReconBreak
    from xmoney.suspense.service import open_suspense, refund_to_float

    db.rollback()
    with db.begin():
        db.add(
            StkCallbackLog(
                id=uuid4(),
                checkout_request_id="ws_CO_PARKED",
                topup_id=None,
                result_code=0,
                disposition=CallbackDisposition.UNMATCHED.value,
                payload={},
            )
        )
    first = run_recon(db)
    assert first.kinds == (BreakKind.MISSING_ON_LEDGER.value,)
    break_id = db.scalar(select(ReconBreak.id).where(ReconBreak.run_id == first.run_id))
    assert break_id is not None
    opened = open_suspense(db, amount_cents=100, reason="from recon", recon_break_id=break_id)
    still_open = run_recon(db)
    assert still_open.kinds == (BreakKind.MISSING_ON_LEDGER.value,)
    refund_to_float(db, item_id=opened.id, reason="return to float")
    quiet = run_recon(db)
    assert quiet.break_count == 0
    assert quiet.kinds == ()
    db.expire_all()
    stamped = db.get(ReconBreak, break_id)
    assert stamped is not None
    assert stamped.quieted_at is not None


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


class _Agrees(_QueryDisagrees):
    def __init__(self) -> None:
        self.queries = 0
        self.rows: list[SettlementRow] = []

    def stk_query(self, checkout_request_id: str) -> StkQueryResult:
        self.queries += 1
        return StkQueryResult(checkout_request_id, False, 0, "paid", Outcome.SUCCESS)

    def list_settlement(self) -> list[SettlementRow]:
        return list(self.rows)


def _park_pending(db: Session, checkout: str, cents: int = 10_000) -> Topup:
    user = register_user(db, handle="reconwait", phone="+254700000099")
    row = Topup(
        id=uuid4(),
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        idempotency_key=f"pending:{checkout}",
        request_hash="a" * 64,
        amount_cents=cents,
        phone_e164=user.phone_e164,
        status=TopupStatus.PENDING.value,
        provider="mock",
        merchant_request_id="m-pending",
        checkout_request_id=checkout,
    )
    with db.begin():
        db.add(row)
    return row


def test_settlement_paid_without_a_callback_is_missing_on_the_ledger(db: Session) -> None:
    parked = _park_pending(db, "ws_CO_DROPPED1")
    rail = _Agrees()
    rail.rows = [
        SettlementRow(
            receipt_number="SBOXDROPPED1",
            amount_cents=10_000,
            checkout_request_id=parked.checkout_request_id,
            phone_e164="+254700000099",
            callback_delivered=False,
        )
    ]
    report = run_recon(db, Rails.of(rail))
    assert report.kinds == (BreakKind.MISSING_ON_LEDGER.value,)


def test_orphan_settlement_row_is_missing_on_the_ledger(db: Session) -> None:
    rail = _Agrees()
    rail.rows = [
        SettlementRow(
            receipt_number="SBOXORPHAN01",
            amount_cents=5_000,
            checkout_request_id=None,
            phone_e164="+254700000000",
            callback_delivered=False,
        )
    ]
    report = run_recon(db, Rails.of(rail))
    assert report.kinds == (BreakKind.MISSING_ON_LEDGER.value,)


def test_stk_query_paid_pending_topup_is_missing_on_the_ledger(db: Session) -> None:
    _park_pending(db, "ws_CO_QUERYPAID")
    rail = _Agrees()
    report = run_recon(db, Rails.of(rail))
    assert report.kinds == (BreakKind.MISSING_ON_LEDGER.value,)
    assert rail.queries == 1


def test_unmatched_callback_and_settlement_do_not_double_count(db: Session) -> None:
    db.rollback()
    with db.begin():
        db.add(
            StkCallbackLog(
                id=uuid4(),
                checkout_request_id="ws_CO_BOTH",
                topup_id=None,
                result_code=0,
                disposition=CallbackDisposition.UNMATCHED.value,
                payload={},
            )
        )
    rail = _Agrees()
    rail.rows = [
        SettlementRow(
            receipt_number="SBOXBOTH0001",
            amount_cents=2_000,
            checkout_request_id="ws_CO_BOTH",
            phone_e164="+254700000000",
            callback_delivered=True,
        )
    ]
    report = run_recon(db, Rails.of(rail))
    assert report.kinds == (BreakKind.MISSING_ON_LEDGER.value,)


def test_closing_suspense_quiets_a_settlement_orphan(db: Session) -> None:
    from sqlalchemy import select

    from xmoney.recon.models import ReconBreak
    from xmoney.suspense.service import open_suspense, refund_to_float

    rail = _Agrees()
    rail.rows = [
        SettlementRow(
            receipt_number="SBOXQUIET01",
            amount_cents=3_000,
            checkout_request_id=None,
            phone_e164="+254700000000",
            callback_delivered=False,
        )
    ]
    first = run_recon(db, Rails.of(rail))
    assert first.kinds == (BreakKind.MISSING_ON_LEDGER.value,)
    break_id = db.scalar(select(ReconBreak.id).where(ReconBreak.run_id == first.run_id))
    assert break_id is not None
    opened = open_suspense(db, amount_cents=3_000, reason="orphan paid", recon_break_id=break_id)
    refund_to_float(db, item_id=opened.id, reason="return to float")
    quiet = run_recon(db, Rails.of(rail))
    assert quiet.kinds == ()
