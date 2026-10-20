# Staff console

The operations console lives at `/console/` on the wallet app and talks to `/v1/console/*`. On a local stack, signed-in staff can apply or refund suspense and reverse a journal entry. A public https demo cannot enable those writes ([ADR 019](../adr/019-console-money-moving.md)).

## Sign in (local)

1. `make demo` (or `make migrate` then `make demo-seed` and `make run` / `make run-web`).
2. Open http://localhost:3000/console/sign-in/
3. Handle `ops`, PIN `2580` unless you set `DEMO_STAFF_HANDLE` / `DEMO_STAFF_PIN`.
4. An empty `DEMO_STAFF_PIN` skips seeding staff, so sign-in has nobody to match.

## What you can do

- Look up a wallet by handle (phone and balance).
- Read that wallet's history and any journal entry's postings.
- See the latest recon run and its classified breaks.
- See the suspense queue and, locally, apply to a handle or refund to the float.
- Propose a reversal from a user's journal, and approve or reject as a second staff user.
- List the outbox dead-letter queue and replay one job.
- Read the staff audit log.

## What you cannot do here

- Post an arbitrary journal entry. That stays behind `SANDBOX_JOURNAL_ENABLED` ([ADR 006](../adr/006-open-demo-protections.md)).
- Apply, refund, or reverse on a public https demo. `CONSOLE_MONEY_MOVING_ENABLED` is off there, and the API refuses to start if it would be on.
- Approve your own reversal. Maker and checker are the staff session, not a string in the body.

## Seed on AWS

`make aws-run-job JOB=demo-reset` truncates application tables (including staff) and seeds wallets plus `@ops` again.
