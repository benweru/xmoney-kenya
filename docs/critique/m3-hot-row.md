# Critique: first M3 slice (hot row)

**Scope**: the PR that adds `allow_negative` and wallet running balances (ADR 010). Written 15 Oct 2026.

## Ordinary

A boolean on the account row and a trigger that increments two bigints. Expected once you admit a stored balance.

## Genuinely impressive

- The float is not locked, and it does not get a running-total `UPDATE` either, so concurrent top-ups for different wallets do not serialize on one row. The test holds one top-up open and still posts another.
- Wallet immutability still holds: only the trigger may change running columns, and only those columns.

## Weakest parts, ranked

1. **No reconciler yet.** Running totals can only drift if the trigger is bypassed. Nothing in this PR walks wallets and compares `running_*` to `SUM(postings)` on a schedule. That is the rest of M3.
2. **System-account reads still `SUM`.** Fine until the float has millions of postings. Then a snapshot that is *not* updated in the posting transaction (fold-from-deltas, or a job) is the follow-up, not putting the hot `UPDATE` back.

## What would raise the bar next

1. Reconciler job that classifies `running != SUM` (should be zero rows).
2. M3 load-test row vs M2, same hardware.
3. Outbox / B2C — not this PR.

## Fed into the plan

Finding 1 is the next M3 slice. This PR is only the hot-row fix.
