"""@handle registration, E.164 phones, and the wallet that comes with each user."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xmoney.errors import HandleTaken, InvalidHandle, InvalidPhone, PhoneTaken, UserNotFound
from xmoney.identity.models import User
from xmoney.identity.service import lookup_handle, register_user
from xmoney.ledger.models import LedgerAccount
from xmoney.ledger.service import get_balance


def test_registration_opens_a_credit_normal_wallet(db: Session) -> None:
    user = register_user(db, handle="@Amina_Ke", phone="+254 712-345-678")
    assert user.handle == "amina_ke"
    assert user.phone_e164 == "+254712345678"
    wallet = db.get(LedgerAccount, user.wallet_account_id)
    assert wallet is not None
    assert wallet.code == f"wallet:{user.id}"
    assert wallet.owner_user_id == user.id
    assert wallet.account_type == "liability"
    assert wallet.normal_side == "credit"
    assert wallet.currency == "KES"
    assert wallet.name == "Wallet @amina_ke"
    assert get_balance(db, wallet.id).balance_cents == 0


def test_handle_uniqueness_is_case_insensitive(db: Session) -> None:
    register_user(db, handle="amina", phone="+254711111111")
    with pytest.raises(HandleTaken):
        register_user(db, handle="AMINA", phone="+254722222222")
    assert db.scalar(select(func.count()).select_from(User)) == 1


def test_phone_uniqueness(db: Session) -> None:
    register_user(db, handle="amina", phone="+254711111111")
    with pytest.raises(PhoneTaken):
        register_user(db, handle="otieno", phone="+254711111111")


def test_lookup_is_case_insensitive_and_hides_the_phone(db: Session) -> None:
    created = register_user(db, handle="amina", phone="+254711111111")
    found = lookup_handle(db, "AMINA")
    assert found.user_id == created.id
    assert found.handle == "amina"
    assert found.wallet_account_id == created.wallet_account_id
    assert not hasattr(found, "phone_e164")
    with pytest.raises(UserNotFound):
        lookup_handle(db, "otieno")


@pytest.mark.parametrize(
    "handle",
    ["ab", "1amina", "am ina", "@", "admin", "a" * 21, "amina!", "support"],
)
def test_rejects_invalid_or_reserved_handles(db: Session, handle: str) -> None:
    with pytest.raises(InvalidHandle):
        register_user(db, handle=handle, phone="+254711111111")
    assert db.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize(
    "phone",
    [
        "0712345678",
        "+25471234567",
        "+255712345678",
        "+254812345678",
        "254712345678",
        "+2547123456789",
        "",
    ],
)
def test_rejects_phones_that_are_not_e164_ke_mobile(db: Session, phone: str) -> None:
    with pytest.raises(InvalidPhone):
        register_user(db, handle="amina", phone=phone)


def test_database_rejects_bad_phone_and_handle(engine) -> None:
    with pytest.raises(IntegrityError, match="ck_users_phone_e164"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO users (id, handle, phone_e164)
                    VALUES (CAST(:id AS uuid), 'amina', '+254812345678')
                    """
                ),
                {"id": str(uuid4())},
            )
    with pytest.raises(IntegrityError, match="ck_users_handle"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO users (id, handle, phone_e164)
                    VALUES (CAST(:id AS uuid), 'ab', '+254711111111')
                    """
                ),
                {"id": str(uuid4())},
            )


def test_database_allows_one_wallet_per_user(db: Session, engine) -> None:
    user = register_user(db, handle="amina", phone="+254711111111")
    with pytest.raises(IntegrityError, match="uq_ledger_accounts_one_owner"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ledger_accounts
                      (id, code, name, account_type, normal_side, currency, owner_user_id)
                    VALUES
                      (CAST(:id AS uuid), :code, 'Second', 'liability', 'credit', 'KES',
                       CAST(:owner AS uuid))
                    """
                ),
                {
                    "id": str(uuid4()),
                    "code": f"wallet:extra-{user.id}",
                    "owner": str(user.id),
                },
            )


def test_concurrent_registration_keeps_a_single_user(engine) -> None:
    workers = 8
    barrier = threading.Barrier(workers)

    def attempt(_: int) -> str:
        barrier.wait(timeout=5)
        session = Session(engine)
        try:
            register_user(session, handle="Amina", phone="+254722222222")
            return "created"
        except HandleTaken:
            return "handle"
        except PhoneTaken:
            return "phone"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(attempt, range(workers)))
    assert results.count("created") == 1
    assert set(results) <= {"created", "handle", "phone"}
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        wallets = session.scalar(
            select(func.count())
            .select_from(LedgerAccount)
            .where(LedgerAccount.owner_user_id.is_not(None))
        )
        assert wallets == 1
