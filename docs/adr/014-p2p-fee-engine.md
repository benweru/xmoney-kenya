# 014. P2P fee engine: versioned schedules, three-leg postings

- Status: Accepted
- Date: 2026-10-20

## Context

[002](002-ledger-design.md) kept cents so a fee can be a fraction of a shilling. `system:fees` already exists. Sends were still two-leg and free, which hides the income side of a wallet. M3 asks for versioned schedules (flat plus percentage, bands, a free P2P allowance) and that each transfer store the version it used.

## Decision

**Append-only `fee_schedules`.** A new tariff is a new row with a higher `version`. Transfers never update. The schedule in force is the highest version whose `effective_from` is not in the future.

**Quote under the sender lock.** `GET /v1/transfers/quote` is a hint. `send` recounts this UTC month's sends after locking the wallets, so a free allowance cannot be double-spent. The sender is debited `amount + fee`; the recipient is credited `amount`; `system:fees` is credited `fee` when the fee is not zero. A zero fee stays two-leg so postings stay positive.

**The transfer row stores `fee_cents` and `fee_schedule_version`.** Replays return that fee even if a newer schedule exists.

**Demo tariff, not a published M-PESA table.** Version 1: KES 100 and under is free, KES 1,000 and under is a flat KES 1, above that is KES 2 plus 0.50% (half-up to the cent). These numbers are ours. They are not Safaricom's or CBK's.

## Consequences

- History for the sender shows the wallet debit, so a KES 120 send with a KES 1 fee appears as − KES 121.00.
- Changing the tariff does not rewrite old transfers.
- Cash-out and top-up fees are still free; they need their own products on the same table later.
- A quote taken before another send can disagree with the fee that is charged. The send is the source of truth.

## Alternatives considered

- **Edit the current schedule in place.** Cheap, but then a transfer's "version" is a lie.
- **Two journal entries (send, then fee).** Two idempotency keys and a crash window between them.
- **Copy Safaricom's published send fees.** We do not have a licence to present those as ours, and they change.
