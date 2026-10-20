# 013. B2C cash-out: hold, then settle or release

- Status: Accepted
- Date: 2026-10-20

## Context

[005](005-stk-topup-state-machine.md) kept cash-outs off the top-up table because they hold funds before calling the rail. [012](012-stk-push-via-outbox.md) sends STK from the outbox; B2C has the same shape. Daraja B2C is asynchronous: a payment request is accepted with a `ConversationID`, then a result (or a timeout) is posted later. A timeout is not a refund. Money may still leave the float after we stopped waiting.

## Decision

**Own table.** `cashouts` with states `initiated` → `pending` → `succeeded` | `failed` | `expired`. `POST /v1/cashouts` locks the wallet, refuses an overdraft, posts the hold (debit wallet, credit `system:mpesa_clearing`), and inserts a `b2c.payment` outbox job in one transaction.

**The worker calls B2C.** Idempotency key `cashout:{id}`, `OriginatorConversationID` is the cash-out id. Accepted → `pending`. A 4xx, or an initiated row that never gets a `ConversationID` before `B2C_EXPIRE_AFTER_SECONDS`, fails and **releases** the hold (debit clearing, credit wallet).

**Result vs timeout.** The result URL settles (debit clearing, credit `system:mpesa_float`) or releases. The timeout URL, and a pending row that ages out, **expire** and leave the hold in clearing. A late paid result still settles; a late unpaid result still releases. There is no sync B2C query in this slice.

**Callbacks.** Token path shares `STK_CALLBACK_TOKEN`. Every payload is stored in `b2c_callbacks`. A success with the wrong amount is `amount_mismatch` and does not settle. Early callbacks that beat the accept response are applied once `pending` is recorded.

## Consequences

- A timed-out cash-out lowers the customer's available balance until a late result or (later) reconciliation/suspense.
- Sandbox B2C needs an initiator and security credential; the mock does not. Mock outcomes still follow the last three digits of the MSISDN, including `037` (timeout) and `099` (dropped result).
- History shows the hold as `cashout` and a release as `cashout_return`. A successful cash-out never credits the wallet again.

## Alternatives considered

- **Treat timeout as failure and refund.** Simple, but it double-pays if M-PESA later pays the customer.
- **Reuse `topups`.** Holds and a second journal entry do not fit that machine.
- **Call B2C on the request thread.** Same crash hole [012](012-stk-push-via-outbox.md) closed for STK.
