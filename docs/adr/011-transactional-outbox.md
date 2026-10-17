# 011. A Postgres transactional outbox with leases, backoff and a dead-letter queue

- Status: Accepted
- Date: 2026-10-17

## Context

Calls to M-PESA happen outside the database and can fail, hang, or be repeated. Today `start_topup` commits the top-up, then calls the rail inline. If the process dies between the two, the top-up sits in `initiated` until a sweep notices. B2C cash-out (M3) and reconciliation make this worse: a lost call there is a lost payout.

The roadmap chose a Postgres outbox over Kafka or Celery, so there is nothing new to run and every line can be explained ([001](001-stack-choice.md)).

## Decision

**One table, `outbox_jobs`.** A job has a `kind`, a JSON `payload`, a `status` of `pending`, `done` or `dead`, an attempt count, and a `run_at` time. An optional `dedupe_key` is unique per kind.

**Enqueue is part of the caller's transaction.** `enqueue` only adds a row to the caller's session and never commits. A job exists if and only if the business change that needs it committed. This is the whole point of the pattern, and a test rolls the transaction back to prove it.

**A claim is a lease, not a status.** `claim_next` picks the oldest due job with `FOR UPDATE SKIP LOCKED`, counts the attempt, and sets `lease_until` and a fresh `lease_token`. Workers never block each other, and a test runs six at once over 40 jobs and checks each ran exactly once.

**The handler runs outside any transaction.** Delivery is at least once, so a handler must be idempotent. The rail calls already take a stable idempotency key.

**A worker killed mid-job needs no cleanup.** Its lease lapses and another worker claims the job. The attempt was counted at claim time, so a job that keeps killing its worker runs out of attempts and is buried instead of looping forever.

**Only the lease holder can finish or fail a job.** `finish` and `fail` match on `lease_token`. A slow worker whose lease was taken over gets `lease_lost` and cannot overwrite the new result.

**Failure backs off, then dead-letters.** After attempt *n* fails, the job waits `base × 2^(n-1)` seconds, capped, with up to 20% shaved off at random so a burst does not retry in lockstep. Defaults are 5 s base, 15 min cap, 6 attempts. A handler can raise `PermanentFailure` to skip the retries. Dead jobs are the DLQ; `replay` puts one back with fresh attempts and counts the replay.

**Workers only claim kinds they have a handler for.** An old worker during a rolling deploy cannot burn attempts on a kind it does not understand.

## Consequences

- The worker is one small process (`xmoney-outbox-worker`) that can run as a second ECS service or a scheduled task.
- At-least-once delivery means every handler needs an idempotency story. That is a rule for new job kinds, not a cost we can remove.
- Ordering is by due time, not strict per account. Handlers that need order for one wallet must not assume it.
- Polling adds up to `OUTBOX_POLL_SECONDS` of latency. `LISTEN/NOTIFY` could cut it later without changing the table.
- This PR ships the engine only. Moving the STK Push, B2C and reconciliation onto it are separate changes, each with its own failure-injection tests.
- Staff replay is a service function today. The console and its audit log come with Console v1.

## Alternatives considered

- **Celery or SQS.** More moving parts, and the "write the row and the job in one transaction" guarantee is lost without a second mechanism.
- **Kafka.** Far more than a demo of this size needs.
- **A `running` status instead of a lease.** A crashed worker would leave jobs stuck in `running` and need a reaper. The lease expires on its own.
- **Counting the attempt on failure instead of on claim.** A job that crashes its worker would never be counted and would retry forever.
