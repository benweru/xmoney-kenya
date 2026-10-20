# Critique: recon ↔ suspense glue

**Scope**: Closing a suspense item stamps `quieted_at` on the linked recon subject so the next run is quiet (ADR 020). Written 21 Oct 2026.

## Ordinary

A resolved flag so yesterday's exception does not reprint.

## Genuinely impressive

- Closing, not opening, is the quiet trigger. Parked value still shows as a recon break until someone applies or refunds (`suspense/service.py` `_quiet_linked_break`).
- The next run skips the subject instead of rewriting history. Old runs keep their rows; only `quieted_at` is stamped.

## Weakest parts, ranked

1. **No auto-open.** Staff still paste a break id (`open_suspense`). Easy to park the cash and forget the id, so recon never quiets.
2. **Drift and trial breaks have no suspense path that makes sense.** Quieting is keyed off `subject_id`. A running-balance stamp would hide a real bug.
3. **Latest console run can still list a quieted row** until recon runs again.

## What would raise the bar next

1. Mock settlement / Transaction Status so paid-but-never-called-back is visible (checkpoint 2).
2. Offer "open suspense" from the recon row in the console (still not auto-post).
3. Chaos evidence that an unmatched callback, park, refund, recon cycle ends at zero breaks.

## Fed into the plan

Finding 1 is a console nicety, not checkpoint 2. Settlement/chaos/load/mutation stay next.
