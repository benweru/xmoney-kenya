# 019. Console money-moving writes: local HTTP only

- Status: Accepted
- Date: 2026-10-21

## Context

[018](018-staff-console.md) gave staff a session and left apply, refund, and reverse on the CLI so the open demo could not mint. Checkpoint 1 chose HTTP for those writes, keyed to the staff session, while keeping a published demo PIN. A public https deployment with `@ops` / `2580` in the README would otherwise let anyone credit a wallet from `/console`.

[006](006-open-demo-protections.md) already refuses `SANDBOX_JOURNAL_ENABLED` when `PUBLIC_BASE_URL` is `https://`, and those routes answer `404 not_found` when the flag is off. There is still no general journal-posting console route.

## Decision

**`CONSOLE_MONEY_MOVING_ENABLED` defaults to true** so `make demo` on a laptop can apply, refund, and reverse from the staff console. Settings refuse to load with the flag on when `PUBLIC_BASE_URL` is `https://`. When the flag is off, the write routes answer `404 not_found`, the same as a route that does not exist.

The writes are:

- `POST /v1/console/suspense/{id}/apply` and `.../refund`
- `POST /v1/console/reversals`, `.../{id}/approve`, and `.../{id}/reject`

Maker and checker are the authenticated staff handle. The client cannot supply them. The maker cannot approve or reject their own reversal. Opening suspense and posting an arbitrary journal entry stay off HTTP.

A public demo must set `CONSOLE_MONEY_MOVING_ENABLED=false` (Terraform does). Restarting with the flag true behind https is a startup failure, not a silent mint.

## Consequences

- Local reviewers can close the suspense queue and reverse a journal entry without the CLI.
- Anyone with the published demo PIN still cannot mint on the public https demo.
- CLI actor strings remain for operators who prefer them; HTTP does not trust those strings.
- CSRF tokens still wait for M5, same as other cookie writes.

## Alternatives considered

- **Keep CLI-only.** Safer for an open demo, but then the console cannot show the money-correctness story.
- **Default the flag off.** Local `make demo` would 404 until someone remembers the env var.
- **Hide the routes instead of 404.** A crawler still finds them; 404 matches ADR 006.
