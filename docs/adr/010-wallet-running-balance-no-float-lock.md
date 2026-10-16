# 010. Do not lock system accounts; running balances on wallets

- Status: Accepted
- Date: 2026-10-15
- Supersedes: the "balances are derived, never stored" sentence of [002](002-ledger-design.md)

## Context

Every top-up posts against `system:mpesa_float`. `_lock_accounts_and_post` took `SELECT … FOR UPDATE` on every account in the entry, so all top-ups across all users ran one at a time. Wallet balances were `SUM(postings)`, which gets slower as history grows. That was finding 2 in [`docs/critique/m0-m1.md`](../critique/m0-m1.md) and the M3 critique follow-up in the roadmap.

Wallets must not go negative. The M-PESA float (and other system accounts) may: they are the other side of customer credits, and locking them does not protect a customer overdraft.

## Decision

**`allow_negative` on `ledger_accounts`.** System accounts (no `owner_user_id`) are `true`. Customer wallets are `false`. `post_entry` locks only accounts that are not allowed to go negative, still in id order. Transfers keep locking both wallets before the balance check.

**Running debit and credit on wallets only.** An `AFTER INSERT` trigger on `postings` updates `running_debit_cents` / `running_credit_cents` when `NOT allow_negative`. The chart-of-accounts immutability trigger still rejects every other update. `get_balance` reads those columns for wallets and still sums postings for system accounts.

**Do not maintain a running total on `mpesa_float`.** Updating that one row on every top-up would re-introduce the hot lock. A later reconciler (not this PR) compares each wallet's running totals to `SUM(postings)` and can still sum the float.

## Consequences

- Concurrent top-ups for different wallets no longer wait on the float row.
- Wallet balance reads are O(1). System-account reads stay aggregates.
- A running total can drift only if the trigger is bypassed; tests compare it to the posting sum. The books still cannot unbalance: the deferred debit=credit trigger is unchanged.
- Load-test proof that this doubled sends/s is the M3 load-test row, not this PR.

## Alternatives considered

- **Lock nothing and trust serializable isolation.** Harder to explain, and overdraft checks would need a different retry story.
- **A running total on every account, including the float.** Correct, but the trigger `UPDATE` of the float row serializes top-ups again.
- **A separate snapshot table rebuilt overnight.** Fine later; a trigger on the wallet row is enough for M3's first slice.
