"""PIN sign-in, one-time codes, lockout, and sessions."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xmoney.auth.models import UserPin
from xmoney.auth.pins import require_new_pin
from xmoney.auth.service import authenticate, start_sign_in, verify_sign_in
from xmoney.errors import (
    AccountLocked,
    InvalidCredentials,
    InvalidOtp,
    InvalidPin,
    NotAuthenticated,
)
from xmoney.identity.models import User
from xmoney.identity.service import register_user
from xmoney.inbox.service import recent_messages

PHONE = "+254712345678"
PIN = "2580"
_CODE_RE = re.compile(r"code is (\d{6})")


def _latest_code(session: Session, phone: str = PHONE) -> str:
    messages = recent_messages(session, phone)
    assert messages, "no sandbox message was delivered"
    match = _CODE_RE.search(messages[0].body)
    assert match is not None
    return match.group(1)


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


@pytest.mark.parametrize("pin", ["123", "1234567", "12a4", " 2580", "1111", "1234", "4321", "0123"])
def test_weak_or_malformed_pins_are_refused(pin: str) -> None:
    with pytest.raises(InvalidPin):
        require_new_pin(pin)


def test_pin_is_stored_as_an_argon2id_hash(db: Session) -> None:
    user = register_user(db, handle="amina", phone=PHONE, pin=PIN)
    stored = db.get(UserPin, user.id)
    assert stored is not None
    assert stored.pin_hash.startswith("$argon2id$")
    assert PIN not in stored.pin_hash


def test_weak_pin_rejects_the_whole_registration(client) -> None:
    response = client.post("/v1/users", json={"handle": "amina", "phone": PHONE, "pin": "0000"})
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_pin"
    assert client.get("/v1/handles/amina").status_code == 404


def test_sign_in_flow_over_http(client) -> None:
    created = client.post("/v1/users", json={"handle": "amina", "phone": PHONE, "pin": PIN})
    assert created.status_code == 201
    assert client.get("/v1/me").status_code == 401

    challenge = client.post("/v1/auth/sign-in", json={"phone": PHONE, "pin": PIN})
    assert challenge.status_code == 200
    assert challenge.json()["delivery"] == "sandbox_inbox"

    inbox = client.get("/v1/sandbox/inbox", params={"phone": PHONE})
    assert inbox.status_code == 200
    match = _CODE_RE.search(inbox.json()[0]["body"])
    assert match is not None

    verified = client.post(
        "/v1/auth/verify",
        json={"challenge_id": challenge.json()["challenge_id"], "code": match.group(1)},
    )
    assert verified.status_code == 200
    assert verified.json()["handle"] == "amina"
    cookie = verified.headers["set-cookie"]
    assert "xmoney_session=" in cookie
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()

    me = client.get("/v1/me")
    assert me.status_code == 200
    assert me.json()["wallet_account_id"] == created.json()["wallet_account_id"]

    assert client.post("/v1/auth/sign-out").status_code == 204
    assert client.get("/v1/me").status_code == 401


def test_session_token_is_useless_after_sign_out(client) -> None:
    client.post("/v1/users", json={"handle": "amina", "phone": PHONE, "pin": PIN})
    challenge = client.post("/v1/auth/sign-in", json={"phone": PHONE, "pin": PIN}).json()
    code = _CODE_RE.search(
        client.get("/v1/sandbox/inbox", params={"phone": PHONE}).json()[0]["body"]
    )
    assert code is not None
    client.post(
        "/v1/auth/verify",
        json={"challenge_id": challenge["challenge_id"], "code": code.group(1)},
    )
    token = client.cookies.get("xmoney_session")
    assert token
    client.post("/v1/auth/sign-out")
    client.cookies.set("xmoney_session", token)
    assert client.get("/v1/me").status_code == 401


def test_wrong_pin_and_unknown_phone_look_the_same(client) -> None:
    client.post("/v1/users", json={"handle": "amina", "phone": PHONE, "pin": PIN})
    wrong = client.post("/v1/auth/sign-in", json={"phone": PHONE, "pin": "9731"})
    unknown = client.post("/v1/auth/sign-in", json={"phone": "+254798765432", "pin": PIN})
    malformed = client.post("/v1/auth/sign-in", json={"phone": "0712", "pin": PIN})
    for response in (wrong, unknown, malformed):
        assert response.status_code == 401
        assert response.json() == wrong.json()
    assert client.get("/v1/sandbox/inbox", params={"phone": PHONE}).json() == []


def test_repeated_wrong_pins_lock_the_account(db: Session) -> None:
    register_user(db, handle="amina", phone=PHONE, pin=PIN)
    now = datetime.now(UTC)
    for _ in range(4):
        with pytest.raises(InvalidCredentials):
            start_sign_in(db, phone=PHONE, pin="9731", now=now)
    with pytest.raises(AccountLocked):
        start_sign_in(db, phone=PHONE, pin="9731", now=now)
    with pytest.raises(AccountLocked):
        start_sign_in(db, phone=PHONE, pin=PIN, now=now + timedelta(minutes=14))
    assert recent_messages(db, PHONE) == []

    start_sign_in(db, phone=PHONE, pin=PIN, now=now + timedelta(minutes=16))
    credential = db.scalar(select(UserPin))
    assert credential is not None
    db.refresh(credential)
    assert credential.failed_attempts == 0
    assert credential.locked_until is None


def test_a_correct_pin_resets_the_wrong_pin_count(db: Session) -> None:
    register_user(db, handle="amina", phone=PHONE, pin=PIN)
    for _ in range(4):
        with pytest.raises(InvalidCredentials):
            start_sign_in(db, phone=PHONE, pin="9731")
    start_sign_in(db, phone=PHONE, pin=PIN)
    for _ in range(4):
        with pytest.raises(InvalidCredentials):
            start_sign_in(db, phone=PHONE, pin="9731")


def test_parallel_wrong_pins_are_each_counted(engine) -> None:
    with Session(engine) as session:
        register_user(session, handle="amina", phone=PHONE, pin=PIN)
    workers = 10
    barrier = threading.Barrier(workers)

    def guess(_: int) -> str:
        barrier.wait(timeout=5)
        with Session(engine) as session:
            try:
                start_sign_in(session, phone=PHONE, pin="9731")
            except InvalidCredentials:
                return "invalid"
            except AccountLocked:
                return "locked"
        return "signed_in"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(guess, range(workers)))
    assert results.count("invalid") == 4
    assert results.count("locked") == 6


def test_a_code_works_once(db: Session) -> None:
    register_user(db, handle="amina", phone=PHONE, pin=PIN)
    challenge = start_sign_in(db, phone=PHONE, pin=PIN)
    code = _latest_code(db)
    issued = verify_sign_in(db, challenge_id=challenge.challenge_id, code=code)
    assert authenticate(db, issued.token).handle == "amina"
    with pytest.raises(InvalidOtp):
        verify_sign_in(db, challenge_id=challenge.challenge_id, code=code)


def test_a_code_expires(db: Session) -> None:
    register_user(db, handle="amina", phone=PHONE, pin=PIN)
    now = datetime.now(UTC)
    challenge = start_sign_in(db, phone=PHONE, pin=PIN, now=now)
    code = _latest_code(db)
    with pytest.raises(InvalidOtp):
        verify_sign_in(
            db, challenge_id=challenge.challenge_id, code=code, now=now + timedelta(minutes=6)
        )


def test_a_code_dies_after_five_wrong_guesses(db: Session) -> None:
    register_user(db, handle="amina", phone=PHONE, pin=PIN)
    challenge = start_sign_in(db, phone=PHONE, pin=PIN)
    code = _latest_code(db)
    for _ in range(5):
        with pytest.raises(InvalidOtp):
            verify_sign_in(db, challenge_id=challenge.challenge_id, code=_wrong(code))
    with pytest.raises(InvalidOtp):
        verify_sign_in(db, challenge_id=challenge.challenge_id, code=code)


def test_sessions_expire(db: Session) -> None:
    register_user(db, handle="amina", phone=PHONE, pin=PIN)
    challenge = start_sign_in(db, phone=PHONE, pin=PIN)
    issued = verify_sign_in(db, challenge_id=challenge.challenge_id, code=_latest_code(db))
    assert authenticate(db, issued.token).handle == "amina"
    with pytest.raises(NotAuthenticated):
        authenticate(db, issued.token, now=issued.expires_at + timedelta(seconds=1))
    with pytest.raises(NotAuthenticated):
        authenticate(db, "not-a-token")


def test_users_without_a_pin_cannot_sign_in(db: Session) -> None:
    register_user(db, handle="amina", phone=PHONE)
    with pytest.raises(InvalidCredentials):
        start_sign_in(db, phone=PHONE, pin=PIN)
    assert db.scalar(select(func.count()).select_from(User)) == 1


def test_inbox_requires_an_e164_phone(client) -> None:
    response = client.get("/v1/sandbox/inbox", params={"phone": "0712345678"})
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_phone"
