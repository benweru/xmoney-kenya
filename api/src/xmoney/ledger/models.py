"""Ledger tables. Balances are not stored; they are summed from postings."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from xmoney.db import Base


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"


class NormalSide(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


NORMAL_SIDE_FOR = {
    AccountType.ASSET: NormalSide.DEBIT,
    AccountType.EXPENSE: NormalSide.DEBIT,
    AccountType.LIABILITY: NormalSide.CREDIT,
    AccountType.EQUITY: NormalSide.CREDIT,
    AccountType.INCOME: NormalSide.CREDIT,
}


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        CheckConstraint("code = lower(code)", name="ck_ledger_accounts_code_lower"),
        CheckConstraint("currency = 'KES'", name="ck_ledger_accounts_currency_kes"),
        CheckConstraint(
            "(account_type IN ('asset', 'expense') AND normal_side = 'debit') OR "
            "(account_type IN ('liability', 'equity', 'income') AND normal_side = 'credit')",
            name="ck_ledger_accounts_normal_side",
        ),
        UniqueConstraint("code", name="uq_ledger_accounts_code"),
        Index(
            "uq_ledger_accounts_one_owner",
            "owner_user_id",
            unique=True,
            postgresql_where=text("owner_user_id IS NOT NULL"),
        ),
        {"comment": "Chart of accounts. Balances are not stored on this table."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    normal_side: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="KES")
    owner_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", name="fk_ledger_accounts_owner_user_id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_journal_entries_idempotency_key"),
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 200",
            name="ck_journal_entries_idempotency_len",
        ),
        CheckConstraint("char_length(request_hash) = 64", name="ck_journal_entries_hash_len"),
        CheckConstraint(
            "char_length(description) BETWEEN 1 AND 500",
            name="ck_journal_entries_description_len",
        ),
        {"comment": "Immutable journal headers. Idempotency keys compare a hash of the postings."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Posting(Base):
    __tablename__ = "postings"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_postings_amount_positive"),
        CheckConstraint("direction IN ('debit', 'credit')", name="ck_postings_direction"),
        CheckConstraint("line_no >= 1", name="ck_postings_line_no"),
        UniqueConstraint("journal_entry_id", "line_no", name="uq_postings_entry_line"),
        Index("ix_postings_account_id", "account_id"),
        Index("ix_postings_journal_entry_id", "journal_entry_id"),
        {"comment": "Immutable debit and credit lines. Amounts are integer KES cents."},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    journal_entry_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "journal_entries.id",
            name="fk_postings_journal_entry_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ledger_accounts.id", name="fk_postings_account_id", ondelete="RESTRICT"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
