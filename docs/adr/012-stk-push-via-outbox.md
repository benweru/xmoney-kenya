# 012. STK Push is sent by the outbox worker, not the API request

- Status: Accepted
- Date: 2026-10-19
- Supersedes: the "same Idempotency-Key retries the push" sentence of [005](005-stk-topup-state-machine.md)

## Context

[011](011-transactional-outbox.md) shipped the outbox engine with no job kinds. `POST /v1/topups` still called Daraja in the request: if the process died after committing the top-up, the prompt was never sent until the client retried the same key.

B2C cash-out has the same shape. The first real job kind is the STK Push, so later rail calls can copy it.

## Decision

**The request writes two rows and returns.** `start_topup` inserts the top-up (`initiated`) and an `stk.push` outbox job in one transaction. The HTTP response is `initiated`. The wallet UI already treats `initiated` and `pending` as "waiting for M-PESA".

**The worker calls the rail.** `xmoney-outbox-worker` claims `stk.push`, calls `stk_push` with idempotency key `topup:{id}`, then `_record_accepted` or `_record_refusal`. A top-up that is no longer `initiated` is a no-op, so a claim after a crash that already recorded the answer does not prompt twice.

**Retries live in the worker.** A 5xx or a network error leaves the top-up `initiated` and the job pending with backoff. A 4xx is `PermanentFailure`: the top-up is `failed` and the job goes to the DLQ. After the last attempt of a retryable error, the top-up is failed too. Replaying `POST /v1/topups` with the same key does not send another push; it returns the existing row. The expire sweep still covers a push that never got through.

**Where the worker runs.** Compose: a `worker` service on the API image. AWS: an ECS Fargate Spot service, scaled to 0 with `make aws-sleep`. GitHub Actions rolls it next to the API.

## Consequences

- `POST /v1/topups` is 201 and `initiated` until a worker is running. An API deploy without the worker leaves prompts unsent until expire.
- Seed scripts and tests that need `pending` call `send_due` (drain the queue in-process) instead of relying on the request thread.
- At-least-once delivery is the rail's idempotency key plus the `initiated` guard, not a new protocol.
- B2C cash-out should enqueue the same way. Reconciliation stays a scheduled job until it needs retries of its own.

## Alternatives considered

- **Keep the rail call on the request and enqueue only on timeout.** Two code paths, and a crash still drops the first prompt.
- **Block the HTTP request until the worker finishes.** That reintroduces request-thread coupling to Daraja.
- **A scheduled `--once` task every minute.** Simpler Terraform, but an STK prompt would wait up to a minute.
