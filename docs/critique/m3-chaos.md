# Critique: chaos suite with counts

**Scope**: 1,000 in-process faults plus a compose worker-kill subset. Written 21 Oct 2026.

## Ordinary

A loop that retries callbacks and a script that kills a container.

## Genuinely impressive

- The 1,000-fault table is a test assertion, not a gist (`test_chaos_suite.py`). Duplicates never mint; dropped STKs credit only after STK Query; unmatched pays become `missing_on_ledger` with unexplained 0.
- Compose kill is the real process crash: the outbox row survives `docker compose kill worker` and completes after `up`.

## Weakest parts, ranked

1. **900 of the 1,000 faults are duplicate callbacks on one top-up.** That is a real fault, but it is not 1,000 independent payments. A reviewer will notice.
2. **No Toxiproxy, no Postgres restart.** The mock drops callbacks internally. A disk-full or `pg_terminate_backend` story is still missing.
3. **Compose subset is one kill.** Rate limits make a 1,000-fault HTTP run against the demo dishonest without turning the limiter off.

## What would raise the bar next

1. Mutation score on the outbox worker and reconciler (checkpoint 2).
2. A local k6 row without waking AWS.
3. One Postgres restart count in compose, after `pool_pre_ping`, with requests lost published honestly.

## Fed into the plan

Finding 1 is acceptable for this slice if the write-up stays honest. Mutation and load stay next. Finding 2 does not block tagging if Ben wants more evidence later.
