# 021. Mock settlement file; Transaction Status looks up a receipt

- Status: Accepted
- Date: 2026-10-21
- Supersedes: the "No Daraja Transaction Status file yet" paragraph of [015](015-reconciliation.md)

## Context

[015](015-reconciliation.md) classified `missing_on_ledger` only from unmatched STK callbacks we already stored. Money M-PESA paid that never called us was invisible: the top finding in [`docs/critique/m3-recon.md`](../critique/m3-recon.md). Daraja Transaction Status is asynchronous (ack, then a POST to `ResultURL`). The sandbox still has no settlement-file download. STK Query remains the sync check for a `CheckoutRequestID` we initiated.

## Decision

**The mock serves a settlement file of paid collections.** `GET /mpesa/settlement/v1/file` (bearer, mock-only) lists successful STKs once they complete, including suffix `099` drops. `PUT /__control/settlement` (control-gated) injects an extra paid row with no STK, so recon can see C2B-shaped orphans. The sandbox host 404s that path; `list_settlement` then returns empty.

**`POST /mpesa/transactionstatus/v1/query` looks up a receipt.** The request body matches Daraja (`CommandID=TransactionStatusQuery`, `IdentifierType=4`). The mock inlines `Result` on the HTTP 200 (sandbox only acknowledges). Recon does not wait on `ResultURL`.

**Recon walks the file, then pending STK Query.** A paid settlement row with no succeeded top-up is `missing_on_ledger` (subject `topup` if we have the push, else `settlement` with a stable UUID). The same checkout is not classified twice if an unmatched callback already named it. A pending, failed, or expired top-up whose STK Query says paid is also `missing_on_ledger`, which is the sandbox-shaped path when there is no file. Classification still does not credit a wallet ([015](015-reconciliation.md)).

## Consequences

- Dropped-callback pays show up on `make recon` against the mock without waiting for the stale-top-up sweep.
- Closing suspense on that break still quiets the subject ([020](020-recon-suspense-glue.md)).
- Querying every non-succeeded top-up plus the succeeded STK Query loop is still acceptable at sandbox scale.

## Alternatives considered

- **Wait for Daraja's ResultURL.** The daily job would need an inbound listener and a timeout. The mock file is the honest stand-in for a settlement extract.
- **Credit from recon when the file says paid.** That repairs in the classifier. Staff still apply from suspense.
- **STK Query on pending only, no file.** That finds our own dropped callbacks and misses injected orphans and the artifact a reviewer can GET.
