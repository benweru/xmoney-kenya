# 020. Closed suspense quiets the recon subject

- Status: Accepted
- Date: 2026-10-21

## Context

[015](015-reconciliation.md) classifies; [016](016-suspense.md) repairs with a compensating entry. An operator copies a break id into `open_suspense`. The next recon run still walks the same unmatched STK callback and writes a new break. The console's "latest run" never goes quiet.

## Decision

**Closing a suspense item (apply or refund) stamps `quieted_at` on the linked recon break and on any other break with the same `subject_type` + `subject_id`.** The next `run_recon` skips those subjects. Classification does not post, and opening suspense does not quiet anything.

`quieted_at` is the only later write on a break row. Runs stay append-only; this stamp is the repair acknowledgement.

## Consequences

- After a close, `make recon` reports no break for that unmatched callback.
- The previous run still lists the break; the console shows it as quieted until a new run replaces latest.
- A close without `recon_break_id` does not quiet recon. Auto-open from every break is still out of scope.

## Alternatives considered

- **Change callback disposition.** Mixes rail history with ops judgement.
- **Quiet while the item is still open.** Hides work that is only parked, not decided.
