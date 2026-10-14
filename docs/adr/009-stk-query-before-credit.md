# 009. Credit an STK top-up only after STK Query confirms

- Status: Accepted
- Date: 2026-10-14
- Supersedes: the "credit on a success callback" part of [005](005-stk-topup-state-machine.md)

## Context

Daraja does not sign STK callbacks. The callback URL ends in a static token (`STK_CALLBACK_TOKEN`) that lands in access logs and CloudFront logs. `CheckoutRequestID` is returned to the client. A success callback that credits the wallet on the token alone lets anyone who has that string mint sandbox shillings for any pending top-up. That was the top finding in [`docs/critique/m0-m1.md`](../critique/m0-m1.md). The state table in 005 does not need a new status: `pending` still means "waiting for a final answer we trust".

## Decision

**A success callback is not a final answer.** `handle_stk_callback` logs it as `recorded`, may keep the receipt number, and leaves the top-up `pending` (or `expired`). It does not post the ledger. The wallet is credited only when `stk_query(CheckoutRequestID)` returns `ResultCode 0`. That query runs immediately after a recorded success (outside the database transaction), when the client polls `GET /v1/topups/{id}`, and when the stale-top-up sweep runs. Under the Daraja mock the query is instant (`delay_ms` defaults to 0).

**Failure callbacks still fail the top-up.** A `ResultCode` other than 0 cannot mint money. Amount mismatches, conflicts, unmatched-early callbacks, row locks, and the `topup:{id}` ledger key stay as in 005.

## Consequences

- A forged success payload with the correct URL token credits nothing unless STK Query independently says the push succeeded.
- A dropped callback is recovered the same way as before: STK Query after `STK_QUERY_AFTER_SECONDS`.
- STK Query still reports no receipt. A receipt arrives on a recorded (or later duplicate) callback.
- An attacker who can also call Daraja as us is out of scope; the token-in-the-URL problem is what this ADR closes. M5 still adds Safaricom's callback IP allowlist.

## Alternatives considered

- **A new `callback_received` status.** Honest, but it forces a trigger and check-constraint migration for a state the client does not need to show. `recorded` on `stk_callbacks` is enough.
- **Keep crediting on the callback and add an IP allowlist only.** The allowlist is M5. The token is already in logs the moment the URL is public.
- **Credit on the callback, then reverse if query disagrees.** That still mints, then hopes a later job notices.
