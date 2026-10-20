# Critique: suspense

**Scope**: CLI that parks unmatched value in `system:suspense` (ADR 016). Written 20 Oct 2026.

## Ordinary

A status column and two compensating entries. Every ledger has a wash account.

## Genuinely impressive

- Opening never credits a customer wallet. The only HTTP-shaped hole would have been that credit; it is not on the API.
- Apply and refund are different postings with different keys, so a retried CLI command cannot double-pay.

## Weakest parts, ranked

1. **Anyone with DB access is staff.** No maker-checker, no actor on the row (`suspense/service.py`).
2. **Opening debiting float is a policy choice.** If the cash is still in clearing, this overstates float until someone notices.
3. **Not wired to recon.** An operator must copy a break id; the job will keep reporting the same unmatched callback.

## What would raise the bar next

1. Mark a break resolved when its suspense item closes, so the next recon run is quiet.
2. Console + staff session, then maker-checker for large applies.
3. Choose float vs clearing from the break kind.

## Fed into the plan

Finding 1 is console v1 / reversals (already on the M3 list). Finding 3 is the next recon/suspense glue PR, not a reason to auto-post.
