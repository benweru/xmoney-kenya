"""The demo seed and the nightly reset."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xmoney.demo import DEMO_USERS, main, reset, seed
from xmoney.errors import InvalidCredentials
from xmoney.history.service import wallet_history
from xmoney.identity.models import User
from xmoney.identity.service import lookup_handle, register_user
from xmoney.ledger.service import get_balance
from xmoney.payments.models import Topup


def _balances(db: Session) -> dict[str, int]:
    db.rollback()
    found = {}
    for demo in DEMO_USERS:
        record = lookup_handle(db, demo.handle)
        found[demo.handle] = get_balance(db, record.wallet_account_id).balance_cents
    return found


def test_seed_adds_three_wallets_with_history(db: Session) -> None:
    assert seed(db) is True
    assert _balances(db) == {"amina": 2_337_00, "baraka": 2_742_00, "wanjiku": 5_899_00}

    topups = db.scalars(select(Topup)).all()
    assert len(topups) == 4
    assert {t.status for t in topups} == {"succeeded"}
    assert {t.provider for t in topups} == {"mock"}
    assert all(t.mpesa_receipt_number and t.mpesa_receipt_number.startswith("SBOX") for t in topups)

    amina = lookup_handle(db, "amina")
    page = wallet_history(
        db, user_id=amina.user_id, wallet_account_id=amina.wallet_account_id, limit=10
    )
    kinds = [item.kind.value for item in page.items]
    assert kinds == ["cashout", "transfer_out", "transfer_in", "transfer_out", "topup"]


def test_seed_runs_once(db: Session) -> None:
    assert seed(db) is True
    assert seed(db) is False
    assert db.scalar(select(func.count()).select_from(User)) == 3


def test_seed_wallets_cannot_sign_in_without_a_seed_pin(client, db: Session) -> None:
    seed(db)
    response = client.post("/v1/auth/sign-in", json={"phone": "+254712345000", "pin": "2580"})
    assert response.status_code == 401
    assert response.json()["error"] == InvalidCredentials.code


def test_a_seed_pin_lets_the_owner_sign_in(
    client, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_SEED_PIN", "2580")
    seed(db)
    response = client.post("/v1/auth/sign-in", json={"phone": "+254712345000", "pin": "2580"})
    assert response.status_code == 200, response.text


def test_reset_removes_visitors_and_restores_the_seed(db: Session) -> None:
    seed(db)
    register_user(db, handle="visitor", phone="+254799000111")
    reset(db)
    handles = set(db.scalars(select(User.handle)).all())
    assert handles == {demo.handle for demo in DEMO_USERS}
    assert _balances(db) == {"amina": 2_337_00, "baraka": 2_742_00, "wanjiku": 5_899_00}


def test_reset_needs_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["reset"])
    assert exit_info.value.code == 2
    assert "pass --yes" in capsys.readouterr().err


def test_the_command_seeds_and_resets(db: Session) -> None:
    main(["seed"])
    main(["seed"])
    main(["reset", "--yes"])
    db.rollback()
    assert db.scalar(select(func.count()).select_from(User)) == 3
