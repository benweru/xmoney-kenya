"""Counted rail faults: duplicates, dropped callbacks, a paused worker, unmatched pays.

The compose driver in infra/chaos/run.py covers docker kill. This file is the
CI-safe bulk of the M3 chaos table: 1,000 injected faults, recon unexplained 0.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from xmoney.identity.service import RegisteredUser, register_user
from xmoney.ledger.service import get_balance, trial_totals
from xmoney.payments.daraja import DarajaHttpProvider
from xmoney.payments.daraja_mock import DarajaMockState, create_daraja_mock_app
from xmoney.payments.deps import Rails
from xmoney.payments.jobs import send_due
from xmoney.payments.models import CallbackDisposition, Topup, TopupStatus
from xmoney.payments.topups import handle_stk_callback, resolve_topup, start_topup
from xmoney.recon.models import BreakKind
from xmoney.recon.service import run_recon

AMOUNT = 50_000
N_DUPLICATE = 900
N_DROP = 40
N_WORKER_PAUSE = 40
N_UNMATCHED = 20


@pytest.fixture
def rail() -> Iterator[tuple[DarajaMockState, DarajaHttpProvider]]:
    state = DarajaMockState()
    mock = TestClient(create_daraja_mock_app(state))
    provider = DarajaHttpProvider(
        base_url="http://testserver",
        consumer_key="sandbox",
        consumer_secret="sandbox",
        shortcode="174379",
        passkey="sandbox-passkey",
        client=mock,
    )
    try:
        yield state, provider
    finally:
        mock.close()


def _start(db: Session, provider: Any, user: RegisteredUser, *, key: str) -> Topup:
    view = start_topup(
        db,
        provider,
        user_id=user.id,
        wallet_account_id=user.wallet_account_id,
        phone=user.phone_e164,
        amount_cents=AMOUNT,
        idempotency_key=key,
    )
    send_due(db, provider)
    topup = db.get(Topup, view.id, populate_existing=True)
    assert topup is not None
    return topup


def _wallet(db: Session, user: RegisteredUser) -> int:
    db.rollback()
    return get_balance(db, user.wallet_account_id).balance_cents


def _later(db: Session, topup_id: UUID, seconds: int) -> datetime:
    created = db.get(Topup, topup_id, populate_existing=True)
    assert created is not None
    return created.created_at + timedelta(seconds=seconds)


def test_a_thousand_injected_faults_leave_zero_unexplained(db: Session, rail) -> None:
    state, provider = rail
    injected = 0
    auto_repaired = 0

    user = register_user(db, handle="chaosdup", phone="+254700000000")
    topup = _start(db, provider, user, key="chaos-dup")
    first = handle_stk_callback(db, provider, state.attempts[0].payload)
    assert first is CallbackDisposition.RECORDED
    credited = resolve_topup(db, provider, topup.id)
    assert credited.status == TopupStatus.SUCCEEDED.value
    payload = state.attempts[0].payload
    for _ in range(N_DUPLICATE):
        again = handle_stk_callback(db, provider, payload)
        assert again is CallbackDisposition.DUPLICATE
        injected += 1
        auto_repaired += 1
    assert _wallet(db, user) == AMOUNT

    for i in range(N_DROP):
        dropped_user = register_user(db, handle=f"chdrop{i:02d}", phone=f"+254700{i:03d}099")
        parked = start_topup(
            db,
            provider,
            user_id=dropped_user.id,
            wallet_account_id=dropped_user.wallet_account_id,
            phone=dropped_user.phone_e164,
            amount_cents=AMOUNT,
            idempotency_key=f"drop-{i}",
        )
        send_due(db, provider)
        injected += 1
        recovered = resolve_topup(db, provider, parked.id, now=_later(db, parked.id, 61))
        assert recovered.status == TopupStatus.SUCCEEDED.value
        auto_repaired += 1

    paused_user = register_user(db, handle="chpause", phone="+254711111110")
    for i in range(N_WORKER_PAUSE):
        parked = start_topup(
            db,
            provider,
            user_id=paused_user.id,
            wallet_account_id=paused_user.wallet_account_id,
            phone=paused_user.phone_e164,
            amount_cents=AMOUNT,
            idempotency_key=f"pause-{i}",
        )
        injected += 1
        send_due(db, provider)
        handle_stk_callback(db, provider, state.attempts[-1].payload)
        resolved = resolve_topup(db, provider, parked.id)
        assert resolved.status == TopupStatus.SUCCEEDED.value
        auto_repaired += 1

    for i in range(N_UNMATCHED):
        injected += 1
        handle_stk_callback(db, provider, _unknown_callback(f"ws_CO_CHAOS{i:04d}"))

    report = run_recon(db, Rails.of(provider))
    assert report.unexplained_count == 0
    assert report.kinds.count(BreakKind.MISSING_ON_LEDGER.value) == N_UNMATCHED
    debits, credits = trial_totals(db)
    assert debits == credits
    assert injected == 1000
    assert auto_repaired == N_DUPLICATE + N_DROP + N_WORKER_PAUSE


def _unknown_callback(checkout: str) -> dict[str, Any]:
    return {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "chaos",
                "CheckoutRequestID": checkout,
                "ResultCode": 0,
                "ResultDesc": "ok",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": 100},
                        {"Name": "MpesaReceiptNumber", "Value": f"SBOX{checkout[-8:]}"},
                        {"Name": "PhoneNumber", "Value": 254700000000},
                    ]
                },
            }
        }
    }
