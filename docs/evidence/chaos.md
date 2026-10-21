# Chaos suite

M3 core evidence: injected rail and process faults, then recon. Unexplained must stay 0 and the ledger must balance.

| Field | Value |
| --- | --- |
| Date | 21 Oct 2026 |
| Environment | GitHub Actions `api` job (pytest) and `compose` job (`infra/chaos/run.py --subset`) |
| Git SHA | this PR (`m3-chaos-suite`); re-check the merge SHA on `main` |
| Commands | `cd api && pytest tests/test_chaos_suite.py`; `python3 infra/chaos/run.py --subset` against `docker compose --profile app` |

AWS was not woken. Worker-kill uses local compose, not ECS `StopTask`.

## Counts

| Source | Faults injected | Mix | Mismatches detected | Auto-repaired | Sent to suspense | Unexplained | Ledger drift |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `tests/test_chaos_suite.py` (api CI) | 1,000 | 900 duplicate STK callbacks, 40 dropped callbacks recovered by STK Query, 40 outbox jobs sent only after a pause, 20 unmatched pays | 20 (`missing_on_ledger`) | 980 | 0 | 0 | 0 |
| `infra/chaos/run.py --subset` (compose CI) | 1 | Worker `docker compose kill` while an STK Push sat in the outbox | 0 | 1 | 0 | 0 | 0 (recon after restart) |

Auto-repaired means the existing state machine absorbed the fault: duplicate disposition, STK Query credit, or the worker finishing the job after it came back. Staff suspense is not auto-opened (ADR 015 / 016). The 20 unmatched pays stay classified for an operator.

Postgres restart mid-run and a Toxiproxy in front of the mock are **not** in this slice. Drop/duplicate/reorder of callbacks are covered in-process by the mock (suffix `099`, replayed payloads) rather than a proxy. Reorder is not a separate row: a late duplicate after credit is the `DUPLICATE` path.

## How to re-run

Local pytest (needs `TEST_DATABASE_URL`, often port 5433 on this machine):

```text
cd api
pytest tests/test_chaos_suite.py
```

Compose subset (stack already up via `make demo`):

```text
python3 infra/chaos/run.py --subset
```

A 1,000-fault loop through HTTP against compose would hit the open-demo rate limits (10 top-ups/user/hour). That is why the bulk counts are pytest, with compose reserved for `docker kill`.
