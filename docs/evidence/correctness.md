# Ledger correctness

M1 leftover evidence: property tests for the invariants, and the manual "broke it on purpose" checks from PRs #5–#8. Mutation scoring with mutmut is **stretch** and is not run on every PR (it would dominate student CI time).

| Field | Value |
| --- | --- |
| Date | 15 Oct 2026 |
| Environment | GitHub Actions `api` job, Postgres 16 |
| Git SHA | this PR (`ledger-proof`); re-check the merge SHA on `main` |
| Commands | `cd api && pytest tests/test_ledger_properties.py tests/test_topups.py tests/test_history.py tests/test_transfers.py tests/test_ledger.py tests/test_ledger_concurrency.py` |

## Hypothesis properties

`api/tests/test_ledger_properties.py` runs **200 examples** each (`@settings(max_examples=200)`):

| Property | What it generates | What must stay true |
| --- | --- | --- |
| Debits equal credits | Random sequences of float→wallet posts | `trial_totals()` is equal; wallet balance equals the sum of those amounts |
| No negative wallet | One funded wallet, then random send amounts to a second handle (including amounts larger than the balance) | `send` either posts or raises `insufficient_funds`; both wallet balances stay ≥ 0; trial totals still match |
| Idempotent replay | One post, then 1–8 replays of the same key and body | Posting count does not increase; `created` is false; balance is unchanged |

These sit on top of the example-based tests (100 concurrent sends, duplicate callbacks, cursor ties). Properties generate sequences; the example tests pin the races.

## "Broke it on purpose"

These were done by hand while #5–#8 were in flight (critique [`m0-m1.md`](../critique/m0-m1.md)). They are not CI jobs: each is a one-line deletion, a failing test, then restore. Re-stated so a reviewer does not have to hunt PR comments.

| Change (reverted; never merged) | Test that failed | Why that proves the lock or cursor |
| --- | --- | --- |
| Drop `.with_for_update()` on the top-up row in `handle_stk_callback` (`payments/topups.py`, the `checkout_request_id` select) | `test_concurrent_duplicate_callbacks_apply_once` | Ten identical callbacks can all pass the "not yet applied" check and each try to credit. The ledger idempotency key `topup:{id}` still stops a second journal entry, but the test asserts a single *applied* callback. Without the row lock, 10 applied instead of 1 (or the status update raced). |
| Encode the history cursor as `created_at` only (drop `journal_entry_id` from `encode_cursor` / the keyset `WHERE`) | `test_entries_from_one_transaction_share_a_timestamp_and_still_page` | Postings in one transaction share `created_at` (stamped with `transaction_timestamp()`). A cursor of time alone cannot tell those five entries apart, so a later page skips or repeats rows. |
| Skip `lock_accounts` before the sender balance check in `transfers/service.py` | `test_100_concurrent_sends_never_overdraw` | 100 concurrent sends of KES 1 from a KES 50 wallet succeed more than 50 times and the wallet goes negative. The journal trigger still balances, but the liability is wrong. |

The production code still has those locks and the `(created_at, journal_entry_id)` cursor. The tests above are the standing proof; this table is the mutation log.

## Mutation score (stretch, not in CI)

Target if run by hand: mutmut on `ledger/service.py` ≥ 70% killed, `transfers/service.py` and `payments/topups.py` ≥ 60%. Surviving equivalent mutants get listed here. **Not published in this PR** — a full mutmut pass is too slow for every student CI run.

## M3: outbox worker and reconciler

mutmut needs `os.fork` (Linux/WSL; [boxed/mutmut#397](https://github.com/boxed/mutmut/issues/397)). It is **not** on the PR `api` job. Config lives in `api/pyproject.toml` `[tool.mutmut]` (worker + `recon/service.py`, tests `test_outbox.py` + `test_recon.py`). Re-run on GitHub: `gh workflow run mutation.yml`.

Until that workflow has a published score, these are the standing "broke it on purpose" checks (reverted; never merged), same style as M1:

| Change (reverted) | Test that failed | Why that proves the code |
| --- | --- | --- |
| `if False and service.finish(...)` in `outbox/worker.py` `run_one` | `test_a_job_runs_once_and_is_done` | The handler ran but the job never moved to done; `run_one` reported `lease_lost` instead of `DONE`. |
| Skip `_settlement_breaks` in `run_recon` | `test_orphan_settlement_row_is_missing_on_the_ledger` | Pending STK Query still finds our own dropped pushes; an orphan receipt with no top-up is invisible without the settlement file. |
| `run.unexplained_count = 1` (after `ReconReport` reads that field) | `test_a_clean_seed_has_no_breaks` | A clean seed must report unexplained 0, not only write 0 on the row and ignore it in the return value. |

`ReconReport.unexplained_count` now uses the run row (`run.unexplained_count`) instead of a hardcoded `0`, so that last mutant is killable.

## Coverage

Line coverage for `ledger/`, `transfers/`, and `payments/topups.py` is in [`hygiene.md`](hygiene.md). The `api` job prints `pytest --cov=xmoney` and fails under 80% overall.
