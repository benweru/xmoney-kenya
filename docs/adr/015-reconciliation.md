# 015. Reconciliation classifies breaks; it does not repair them yet

- Status: Accepted
- Date: 2026-10-20

## Context

M3's claim is that every shilling is accounted for when M-PESA misbehaves. The ledger cannot be edited, wallets keep running totals that could only drift if a trigger is bypassed ([010](010-wallet-running-balance-no-float-lock.md)), and some STK callbacks are already stored as `amount_mismatch` or `unmatched` with nobody to take them. Suspense and the console come after we can *name* the differences.

## Decision

**A scheduled job (`xmoney-recon`) writes one `recon_runs` row and zero or more `recon_breaks`.** It does not post to `system:suspense` and it does not credit or debit wallets. Staff (later) repair from the break list.

**Kinds in this slice:**

- `running_balance_drift`: a wallet's trigger totals disagree with `SUM(postings)`.
- `trial_unbalanced`: all posting debits ≠ credits (should be impossible).
- `amount_mismatch` / `missing_on_ledger`: STK callbacks we already stored as such.
- `missing_on_rail`: a succeeded top-up whose STK Query no longer says paid.
- `in_flight_hold`: an expired cash-out still in clearing.

**Unexplained is a count, not a kind.** This slice classifies everything it finds, so `unexplained_count` is 0. A later chaos run that produces a row we cannot name will increment it.

**No Daraja Transaction Status file yet.** Sandbox Transaction Status needs an initiator; the mock has no settlement file. STK Query on our succeeded top-ups is the rail check we can run today. A mock settlement file is a follow-up, not a blocker for classifying the books.

EventBridge runs the job at 04:00 Nairobi (after the 03:00 demo reset) while the stack is awake.

## Consequences

- A clean demo seed must recon to zero breaks.
- Repairing a break is a new compensating entry (suspense / reversals), not an update.
- Querying every succeeded top-up on every run is fine at sandbox scale.

## Alternatives considered

- **Auto-post to suspense.** Hides the classification step that a reviewer wants to see, and can move money the operator has not looked at.
- **Wait for a full settlement file.** We would have no reconciler until Daraja Transaction Status is wired, including on the mock.
