# Critique: STK Query before credit

**Scope**: the `stk-query-confirm` PR, read against `main` at `64dc819`. Written 14 Oct 2026.

## Ordinary

Logging every callback and calling STK Query when one is dropped is what 005 already did. This PR only changes *when* a `ResultCode 0` body is allowed to post.

## Genuinely impressive

- **The forged-callback test actually forges.** `test_a_forged_success_callback_with_the_correct_token_credits_nothing` posts a `ResultCode 0` body for a real `CheckoutRequestID` with the real token, then asserts the wallet is still 0 because STK Query says the push is still processing (`payments/topups.py` `_ingest_callback`, `_confirm_with_query`). That is the interview question from [m0-m1](m0-m1.md) finding 1, in pytest.
- Exactly-once application, unmatched-early callbacks, lock ordering, and the ledger trigger are unchanged. Concurrent duplicates still credit once; they now report `recorded` instead of `applied`.

## Weakest parts, ranked

1. **Failure callbacks still win without a query.** `_ingest_callback` calls `_apply` for any non-zero `ResultCode`. Anyone with the URL token can fail a pending top-up that the customer later paid. The wallet does not mint, but the customer is not credited unless a later query or late success path runs. `resolve_topup` will not query a `failed` row. This is a denial of credit, not a mint, and it is still a shared-string trust issue.
2. **`recorded` is a log disposition, not a status.** Polling has to notice a recorded success and query immediately. If that lookup is wrong, a genuine callback sits in `pending` until `STK_QUERY_AFTER_SECONDS`. The GET path does this via `_has_recorded_success`; a missed index is not the problem today (the table is small), the implicit state is.

## What would raise the bar next

1. Treat a failure callback the same as a success: record it, confirm with STK Query, and only then mark `failed`. Same size as this PR.
2. Rotate `STK_CALLBACK_TOKEN` and stop putting it in the path (M5 still has the IP allowlist).
3. The hot-row / running-balance work already queued as the M3 critique follow-up.

## Fed into the plan

Finding 1 (fail-without-query) is not a new roadmap row. M5's callback IP allowlist and a follow-up that confirms failures with STK Query both close it. Finding 2 of m0-m1 (the `mpesa_float` hot row) is still the M3 critique follow-up.
