# 005. STK top-ups: a state machine with exactly-once callbacks

- Status: Accepted (credit-on-callback superseded by [009](009-stk-query-before-credit.md))
- Date: 2026-10-13

## Context

An STK Push top-up is asynchronous. The API asks Daraja to prompt the customer's phone. Seconds or minutes later, Daraja posts a result to our callback URL, or it never does. In practice callbacks arrive twice, arrive before the push response has been saved, arrive after we stopped waiting, or are lost. A wallet that credits twice, or never credits a customer who paid, is broken either way.

## Decision

**One row per top-up, with a state machine** (`topups.status`):

| From | To | When |
| --- | --- | --- |
| `initiated` | `pending` | Daraja accepted the push and gave us a `CheckoutRequestID` |
| `initiated` | `failed` | Daraja refused the push (HTTP 4xx) |
| `initiated` | `expired` | the push never got through before the deadline |
| `pending` | `succeeded` / `failed` | STK Query confirms paid, or a failure callback / query gives a final no |
| `pending` | `expired` | no final answer within `STK_EXPIRE_AFTER_SECONDS` |
| `expired` | `succeeded` / `failed` | a late callback gives a final answer |

`expired` means "we stopped waiting", not "no money moved". A customer who paid must still be credited when the late callback arrives. `succeeded` and `failed` are final. A trigger in Postgres enforces this table and refuses edits to the amount, the owner, and the request, and any change to `checkout_request_id` or `journal_entry_id` once set. The service checks the same table first.

**Exactly once.** The callback handler locks the top-up row (`SELECT … FOR UPDATE` on `checkout_request_id`). A success callback is `recorded`, not credited; [009](009-stk-query-before-credit.md) requires STK Query before the wallet moves. Failure callbacks can still fail the top-up. The wallet credit (debit `system:mpesa_float`, credit the wallet) is posted with `post_entry_in_transaction`, so the status change and the journal entry commit together or not at all. Its ledger idempotency key is `topup:{id}`, so even a bug that applied twice could not post twice. Every callback is kept in `stk_callbacks` with what it did: `recorded`, `applied`, `duplicate`, `conflict` (it contradicts the final state), `amount_mismatch` (held for reconciliation, not credited), or `unmatched`.

**Out of order.** A callback for an unknown `CheckoutRequestID` is logged as `unmatched` and acknowledged. When the push response is then saved, any unmatched callbacks for that id are applied in the same transaction.

**Dropped callbacks.** A top-up still waiting after `STK_QUERY_AFTER_SECONDS` is checked with Daraja's STK Query API, at most once per `STK_QUERY_INTERVAL_SECONDS`. That happens when the client polls `GET /v1/topups/{id}` and when `xmoney-resolve-topups` sweeps. Rail calls never run inside a database transaction.

**Client idempotency.** `POST /v1/topups` requires an `Idempotency-Key`, unique per user. A replay returns the same top-up, and the same key with a different body is a 409. If Daraja did not answer at all, the top-up stays `initiated` and the same key retries the push.

## Consequences

- Duplicate, early, late, and lost callbacks have tests, including 10 concurrent copies of one callback.
- Daraja does not sign callbacks, and a customer can see their own `CheckoutRequestID`. Without a check, they could post a fake "paid" callback for their own top-up. The callback URL therefore ends in a secret token (`STK_CALLBACK_TOKEN`, random per process unless set), and a wrong token is a 404. The token shows up in access logs, so anyone who can read the logs could forge a callback. M5 adds Safaricom's published callback IP allowlist on top.
- STK Query reports no receipt number. A top-up resolved by query gets its receipt from a later duplicate callback, if one comes.
- `amount_mismatch`, `conflict`, and `unmatched` callbacks are visible in `stk_callbacks` but are nobody's job yet. M3's reconciliation and suspense queue take them over.
- The sweep is a command, not a scheduled job. M3's worker and EventBridge Scheduler will run it.

## Alternatives considered

- **Credit on the push response.** The push being accepted only means the prompt was sent.
- **Trust the callback with no row lock, relying on the ledger key.** The ledger would not double-post, but two callbacks could both "apply" and race on the status.
- **Treat expired as final.** Simple, but it strands money from customers who approved late.
- **A generic payments table for top-ups and cash-outs.** B2C cash-outs (M3) hold funds before calling the rail and have different states. They will get their own table.
