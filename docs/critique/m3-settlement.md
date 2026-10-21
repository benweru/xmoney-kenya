# Critique: mock settlement / Transaction Status

**Scope**: Mock settlement file, Transaction Status lookup, recon `missing_on_ledger` from paid-but-never-called-back (ADR 021). Written 21 Oct 2026.

## Ordinary

Another GET the mock answers, and another loop in the daily job.

## Genuinely impressive

- `missing_on_ledger` is now what the rail paid, not only unmatched callbacks we stored (`recon/service.py` `_settlement_breaks`, `_pending_paid`). A dropped STK (suffix 099) is on the file and classified without waiting for the sweep (`test_recon.py`, `test_daraja_mock.py`).
- The mock inlines Transaction Status `Result`; sandbox ack-without-Result stays honest. Recon does not pretend Daraja returns a file.

## Weakest parts, ranked

1. **Sandbox still has no extract.** Pending STK Query finds our own unpaid-looking top-ups if Query says paid. Orphans that never hit our STK table stay mock-only.
2. **Every non-succeeded top-up is queried.** Fine at demo scale; a long awake period is chatty, same class of problem as the succeeded STK Query loop.
3. **Injected rows share the in-memory mock.** Two API tasks would not see each other's file. Compose is one mock process.

## What would raise the bar next

1. Chaos evidence that drop-callback → recon break → suspense → quiet actually happens under faults.
2. Console "open suspense" from the recon row (still not auto-post).
3. Persist mock settlement across process restart if the demo mock is a separate container with no volume.

## Fed into the plan

Finding 1 is checkpoint 2 chaos. This PR closes the m3-recon top finding.
