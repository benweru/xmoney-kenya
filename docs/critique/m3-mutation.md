# Critique: mutation on worker and recon

**Scope**: Manual mutants on `outbox/worker.py` and `recon/service.py`, mutmut config + workflow_dispatch (not every PR). Written 21 Oct 2026.

## Ordinary

Three one-line deletions and a GitHub workflow someone has to click.

## Genuinely impressive

- Skipping settlement still finds dropped STKs via pending Query, and the orphan test is what actually dies. That is the point of ADR 021 (`test_orphan_settlement_row_is_missing_on_the_ledger`).
- `ReconReport` used to return unexplained `0` even if the row said otherwise. The report now reads the row, so a lying count is testable.

## Weakest parts, ranked

1. **No mutmut percentage yet.** Native Windows cannot run mutmut. The score is a Linux job that has not published a killed/survived table.
2. **Worker mutant is one finish() skip.** It does not cover DLQ, lease steal, or `drain` limit.
3. **Chaos suite is excluded from mutmut tests** so the run does not take another 100s per mutant, which also means chaos assertions do not kill recon mutants.

## What would raise the bar next

1. Publish the `mutation.yml` artifact numbers on `main`.
2. Local k6 row without waking AWS.
3. Include `test_chaos_suite.py` in a weekly mutmut, not per mutant in PR CI.

## Fed into the plan

Finding 1 is the remaining checkpoint 2 evidence gap if Ben wants a percentage before tagging M3.
