"""Staff console: a wallet cookie is not enough; money-moving writes need the staff session."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from xmoney.console.models import StaffAuditEvent, StaffUser
from xmoney.console.service import DEFAULT_STAFF_HANDLE, DEFAULT_STAFF_PIN, seed_staff_user
from xmoney.demo import seed
from xmoney.ledger.money import Direction, PostCommand, PostingLine
from xmoney.ledger.service import get_balance, post_entry
from xmoney.ledger.system import MPESA_FLOAT
from xmoney.outbox import service as outbox
from xmoney.outbox.models import OutboxJob
from xmoney.outbox.worker import Outcome, run_one
from xmoney.recon.service import run_recon
from xmoney.suspense.service import open_suspense
from xmoney.transfers.models import Transfer
from xmoney.transfers.service import send

PIN = "2580"
T0 = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
KIND = "test.job"


def _boom(_claim: object) -> None:
    raise RuntimeError("nope")


def _staff(client: TestClient, db: Session) -> None:
    seed_staff_user(db, handle="ops", pin=PIN)
    response = client.post("/v1/console/sign-in", json={"handle": "ops", "pin": PIN})
    assert response.status_code == 200, response.text
    assert response.json()["handle"] == "ops"


def test_wallet_session_cannot_open_the_console(client: TestClient, sign_up) -> None:
    sign_up("amina", "+254712345001")
    assert client.get("/v1/me").status_code == 200
    denied = client.get("/v1/console/me")
    assert denied.status_code == 401
    assert denied.json()["error"] == "not_authenticated"


def test_unsigned_staff_routes_are_401(client: TestClient) -> None:
    assert client.get("/v1/console/me").status_code == 401
    assert client.get("/v1/console/recon/latest").status_code == 401
    replay = client.post("/v1/console/outbox/00000000-0000-0000-0000-000000000001/replay")
    assert replay.status_code == 401


def test_staff_sign_in_issues_a_cookie_and_me(client: TestClient, db: Session) -> None:
    _staff(client, db)
    me = client.get("/v1/console/me")
    assert me.status_code == 200
    assert me.json()["handle"] == "ops"
    client.post("/v1/console/sign-out")
    assert client.get("/v1/console/me").status_code == 401


def test_wrong_staff_pins_lock_the_account(client: TestClient, db: Session) -> None:
    seed_staff_user(db, handle="ops", pin=PIN)
    for _ in range(5):
        bad = client.post("/v1/console/sign-in", json={"handle": "ops", "pin": "2591"})
        assert bad.status_code in {401, 423}
    locked = client.post("/v1/console/sign-in", json={"handle": "ops", "pin": PIN})
    assert locked.status_code == 423
    assert locked.json()["error"] == "account_locked"


def test_unknown_handle_looks_the_same_as_a_wrong_pin(client: TestClient, db: Session) -> None:
    seed_staff_user(db, handle="ops", pin=PIN)
    missing = client.post("/v1/console/sign-in", json={"handle": "ghost", "pin": PIN})
    assert missing.status_code == 401
    assert missing.json()["error"] == "invalid_credentials"


def test_lookup_shows_phone_and_empty_ledger_for_a_new_wallet(
    client: TestClient, db: Session, sign_up
) -> None:
    wallet = sign_up("amina", "+254712345001")
    _staff(client, db)
    found = client.get("/v1/console/users", params={"handle": "amina"})
    assert found.status_code == 200
    body = found.json()
    assert body["handle"] == "amina"
    assert body["phone"] == "+254712345001"
    assert body["user_id"] == wallet["user_id"]
    ledger = client.get(f"/v1/console/users/{body['user_id']}/ledger")
    assert ledger.status_code == 200
    assert ledger.json()["items"] == []
    empty = client.get("/v1/console/users", params={"handle": "nobody"})
    assert empty.status_code == 404


def test_recon_suspense_and_audit_are_readable(client: TestClient, db: Session) -> None:
    seed(db)
    run_recon(db)
    _staff(client, db)
    recon = client.get("/v1/console/recon/latest")
    assert recon.status_code == 200
    assert recon.json()["run_id"] is not None
    assert recon.json()["unexplained_count"] == 0
    suspense = client.get("/v1/console/suspense")
    assert suspense.status_code == 200
    assert suspense.json() == []
    audit = client.get("/v1/console/audit")
    assert audit.status_code == 200
    actions = {row["action"] for row in audit.json()}
    assert "sign_in" in actions
    assert "view_recon" in actions


def test_seeded_wallet_ledger_opens_a_journal(client: TestClient, db: Session) -> None:
    seed(db)
    _staff(client, db)
    found = client.get("/v1/console/users", params={"handle": "amina"})
    user_id = found.json()["user_id"]
    ledger = client.get(f"/v1/console/users/{user_id}/ledger")
    items = ledger.json()["items"]
    assert items
    journal = client.get(f"/v1/console/journal/{items[0]['entry_id']}")
    assert journal.status_code == 200
    lines = journal.json()["postings"]
    assert lines
    assert sum(p["amount_cents"] for p in lines if p["direction"] == "debit") == sum(
        p["amount_cents"] for p in lines if p["direction"] == "credit"
    )


def test_dlq_replay_puts_a_dead_job_back(client: TestClient, db: Session) -> None:
    db.rollback()
    with db.begin():
        job_id = outbox.enqueue(db, KIND, {"n": 1}, max_attempts=1, now=T0)
    assert run_one(db, {KIND: _boom}, now=T0) is Outcome.DEAD
    _staff(client, db)
    listed = client.get("/v1/console/outbox/dlq")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == str(job_id)
    replay = client.post(f"/v1/console/outbox/{job_id}/replay")
    assert replay.status_code == 204
    assert client.get("/v1/console/outbox/dlq").json() == []
    db.expire_all()
    job = db.get(OutboxJob, job_id)
    assert job is not None
    assert job.status == "pending"
    missing = client.post(f"/v1/console/outbox/{UUID(int=1)}/replay")
    assert missing.status_code == 404


def test_console_has_no_general_journal_mint(client: TestClient, db: Session) -> None:
    _staff(client, db)
    assert client.post("/v1/sandbox/journal-entries", json={}).status_code == 404
    assert client.post("/v1/console/suspense").status_code == 405


def test_seed_creates_ops_once(db: Session) -> None:
    assert seed_staff_user(db) is True
    assert seed_staff_user(db) is False
    handle = db.scalar(select(StaffUser.handle).where(StaffUser.handle == DEFAULT_STAFF_HANDLE))
    assert handle == "ops"
    assert DEFAULT_STAFF_PIN == PIN


def test_audit_events_are_written(client: TestClient, db: Session) -> None:
    _staff(client, db)
    client.get("/v1/console/recon/latest")
    assert db.scalar(select(StaffAuditEvent.id)) is not None


def test_demo_seed_includes_staff(db: Session) -> None:
    assert seed(db) is True
    assert db.scalar(select(StaffUser.handle).where(StaffUser.handle == "ops")) == "ops"


def test_staff_can_apply_suspense(client: TestClient, db: Session, sign_up) -> None:
    wallet = sign_up("amina", "+254712345001")
    opened = open_suspense(db, amount_cents=1_500, reason="unmatched STK receipt")
    _staff(client, db)
    applied = client.post(
        f"/v1/console/suspense/{opened.id}/apply",
        json={"handle": "amina", "reason": "customer called"},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert get_balance(db, UUID(wallet["wallet_account_id"])).balance_cents == 1_500
    audit = client.get("/v1/console/audit")
    assert "apply_suspense" in {row["action"] for row in audit.json()}


def test_wallet_cookie_cannot_apply_or_reverse(client: TestClient, db: Session, sign_up) -> None:
    sign_up("amina", "+254712345001")
    opened = open_suspense(db, amount_cents=400, reason="parked")
    apply = client.post(
        f"/v1/console/suspense/{opened.id}/apply",
        json={"handle": "amina", "reason": "nope"},
    )
    assert apply.status_code == 401
    assert apply.json()["error"] == "not_authenticated"
    reverse = client.post(
        "/v1/console/reversals",
        json={
            "original_journal_entry_id": "00000000-0000-0000-0000-000000000001",
            "reason": "nope",
        },
    )
    assert reverse.status_code == 401


def test_money_moving_flag_off_is_404(client: TestClient, db: Session, sign_up, configure) -> None:
    sign_up("amina", "+254712345001")
    opened = open_suspense(db, amount_cents=200, reason="parked")
    _staff(client, db)
    configure(CONSOLE_MONEY_MOVING_ENABLED="false")
    apply = client.post(
        f"/v1/console/suspense/{opened.id}/apply",
        json={"handle": "amina", "reason": "customer called"},
    )
    assert apply.status_code == 404
    assert apply.json()["error"] == "not_found"
    refund = client.post(f"/v1/console/suspense/{opened.id}/refund", json={"reason": "return"})
    assert refund.status_code == 404
    reverse = client.post(
        "/v1/console/reversals",
        json={
            "original_journal_entry_id": "00000000-0000-0000-0000-000000000001",
            "reason": "nope",
        },
    )
    assert reverse.status_code == 404


def test_reversal_maker_checker_uses_two_staff(
    client: TestClient, db: Session, sign_up, configure
) -> None:
    configure(REVERSAL_MAKER_CHECKER_CENTS="1000")
    amina = sign_up("amina", "+254712345001")
    baraka = sign_up("baraka", "+254722345001")
    post_entry(
        db,
        PostCommand(
            idempotency_key="fund-console",
            description="Test top-up",
            postings=(
                PostingLine(MPESA_FLOAT.id, Direction.DEBIT, 50_000),
                PostingLine(UUID(amina["wallet_account_id"]), Direction.CREDIT, 50_000),
            ),
        ),
    )
    sent = send(
        db,
        sender_user_id=UUID(amina["user_id"]),
        sender_handle="amina",
        sender_wallet_id=UUID(amina["wallet_account_id"]),
        to_handle="baraka",
        amount_cents=20_000,
        idempotency_key="s-console",
    )
    transfer = db.get(Transfer, sent.id)
    assert transfer is not None
    _staff(client, db)
    seed_staff_user(db, handle="checker", pin=PIN)
    proposed = client.post(
        "/v1/console/reversals",
        json={
            "original_journal_entry_id": str(transfer.journal_entry_id),
            "reason": "wrong payee",
            "maker": "forged",
        },
    )
    assert proposed.status_code == 422
    proposed = client.post(
        "/v1/console/reversals",
        json={
            "original_journal_entry_id": str(transfer.journal_entry_id),
            "reason": "wrong payee",
        },
    )
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["status"] == "proposed"
    assert body["maker"] == "ops"
    assert body["needs_checker"] is True
    self_approve = client.post(f"/v1/console/reversals/{body['id']}/approve")
    assert self_approve.status_code == 422
    client.post("/v1/console/sign-out")
    checker = client.post("/v1/console/sign-in", json={"handle": "checker", "pin": PIN})
    assert checker.status_code == 200, checker.text
    posted = client.post(f"/v1/console/reversals/{body['id']}/approve")
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "posted"
    assert posted.json()["checker"] == "checker"
    assert get_balance(db, UUID(baraka["wallet_account_id"])).balance_cents == 0
    audit = client.get("/v1/console/audit")
    actions = {row["action"] for row in audit.json()}
    assert "propose_reversal" in actions
    assert "approve_reversal" in actions
