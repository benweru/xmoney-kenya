# Staff console

The operations console lives at `/console/` on the wallet app and talks to `/v1/console/*`. It does not move money except replaying a dead outbox job.

## Sign in (local)

1. `make demo` (or `make migrate` then `make demo-seed` and `make run` / `make run-web`).
2. Open http://localhost:3000/console/sign-in/
3. Handle `ops`, PIN `2580` unless you set `DEMO_STAFF_HANDLE` / `DEMO_STAFF_PIN`.
4. An empty `DEMO_STAFF_PIN` skips seeding staff, so sign-in has nobody to match.

## What you can do

- Look up a wallet by handle (phone and balance).
- Read that wallet's history and any journal entry's postings.
- See the latest recon run and its classified breaks.
- See the suspense queue (apply and refund stay on `make suspense`).
- List the outbox dead-letter queue and replay one job.
- Read the staff audit log.

## What you cannot do here

- Credit a wallet, apply or refund suspense, or reverse a journal entry. Those stay on the CLI so the open demo cannot mint ([ADR 006](../adr/006-open-demo-protections.md), [016](../adr/016-suspense.md), [017](../adr/017-reversals.md), [018](../adr/018-staff-console.md)).

## Seed on AWS

`make aws-run-job JOB=demo-reset` truncates application tables (including staff) and seeds wallets plus `@ops` again.
