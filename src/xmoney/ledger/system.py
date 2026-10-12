"""Chart of accounts that exist before any user does.

Float is the cash we would hold at M-PESA (asset). Clearing is in-flight STK
or B2C value that has not settled into the float (asset). Fees are income.
Suspense holds value we owe but cannot yet apply to a wallet (liability).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from xmoney.ledger.models import AccountType, NormalSide


@dataclass(frozen=True)
class SystemAccount:
    id: UUID
    code: str
    name: str
    account_type: AccountType
    normal_side: NormalSide


MPESA_FLOAT = SystemAccount(
    UUID("00000000-0000-4000-8000-000000000001"),
    "system:mpesa_float",
    "M-PESA float",
    AccountType.ASSET,
    NormalSide.DEBIT,
)
MPESA_CLEARING = SystemAccount(
    UUID("00000000-0000-4000-8000-000000000002"),
    "system:mpesa_clearing",
    "M-PESA clearing",
    AccountType.ASSET,
    NormalSide.DEBIT,
)
FEES = SystemAccount(
    UUID("00000000-0000-4000-8000-000000000003"),
    "system:fees",
    "Fee income",
    AccountType.INCOME,
    NormalSide.CREDIT,
)
SUSPENSE = SystemAccount(
    UUID("00000000-0000-4000-8000-000000000004"),
    "system:suspense",
    "Suspense",
    AccountType.LIABILITY,
    NormalSide.CREDIT,
)

SYSTEM_ACCOUNTS: tuple[SystemAccount, ...] = (MPESA_FLOAT, MPESA_CLEARING, FEES, SUSPENSE)


def wallet_code(user_id: UUID) -> str:
    return f"wallet:{user_id}"
