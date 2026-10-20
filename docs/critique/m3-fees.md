# Critique: P2P fee engine

**Scope**: the PR that adds `fee_schedules` and charges P2P sends (ADR 014). Written 20 Oct 2026.

## Ordinary

A config table and `amount * bps / 10000`. Every payments app has a fee function.

## Genuinely impressive

- The fee version lives on the transfer row, and a later `publish_p2p_schedule` does not change it. Replay returns the fee that was charged.
- The three-leg posting is the same shape as the README's collection example, and a zero fee does not insert a zero posting (the ledger would reject it).
- The free-allowance count is taken after the wallet lock, so two concurrent sends cannot both be "the third free one".

## Weakest parts, ranked

1. **Quote is best-effort.** `GET /v1/transfers/quote` does not lock. Two tabs can both show "free" and the second send pays. The send is correct; the UI can lie for a moment (`transfers/routes.py` `quote_transfer`).
2. **Only P2P.** Cash-out of KES 500 is still free. A reviewer will ask why B2C has no tariff.
3. **UTC calendar month.** Nairobi is UTC+3, so the allowance resets at 03:00 local, not midnight.

## What would raise the bar next

1. Cash-out (and later STK) products on the same `fee_schedules` table.
2. Show `fee_cents` on the history API so the UI can split "sent KES 120" from "KES 1 fee" instead of − KES 121.
3. Reconciler still missing (unchanged from [m3-hot-row](m3-hot-row.md)).

## Fed into the plan

Finding 1 is acceptable for a demo. Finding 2 is the next fee slice if we charge cash-out before console v1. The roadmap already lists reconciliation after fees; this PR does not change that order.
