# Critique: first reconciler

**Scope**: the PR that adds `recon_runs` / `recon_breaks` and `xmoney-recon` (ADR 015). Written 20 Oct 2026.

## Ordinary

A batch job that SELECTs and inserts findings. Cron plus a table.

## Genuinely impressive

- It refuses to "fix" money. Classification without a compensating entry is the honest first step.
- Wallet running totals vs `SUM(postings)` is the check ADR 010 promised, and the test actually bypasses the trigger the way an operator accident would.

## Weakest parts, ranked

1. **No settlement file.** `missing_on_ledger` is only unmatched STK callbacks we already stored. Money M-PESA paid that never called us is invisible (`recon/service.py` `_callback_breaks`).
2. **STK Query on every succeeded top-up.** After a nightly reset this is a handful of rows. After a long awake period it is a chatty loop against Daraja.
3. **No HTTP list.** The console cannot show breaks until a later PR. The job only logs a count.

## What would raise the bar next

1. A mock settlement file (and sandbox Transaction Status) so `missing_on_ledger` is what M-PESA paid, not only what called back.
2. Suspense: one staff action posts a classified break to `system:suspense` with a reason.
3. Console v1: list the latest run's breaks.

## Fed into the plan

Finding 1 is the next recon slice. Suspense stays after classification, as the roadmap already ordered it. This PR does not change that order.
