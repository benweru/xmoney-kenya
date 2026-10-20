# 018. Staff console: a separate session, read-only money views, DLQ replay

- Status: Accepted
- Date: 2026-10-20

## Context

M3 needs a back-office a reviewer can click: user lookup, ledger explorer, recon breaks, the suspense queue, the outbox DLQ, and an audit log. Wallet sign-in is a phone, a PIN, and a one-time code in the sandbox inbox (ADR 004). That identity is a customer. Reversals and suspense still take actor strings on the CLI (ADRs 016 and 017). Putting those CLIs on HTTP without a staff session would let the open demo mint.

## Decision

- **Staff are not wallet users.** `staff_users` is a separate table: handle + Argon2id PIN, the same lockout as customers, no phone, no OTP. A correct PIN issues `xmoney_staff_session`. A wallet cookie is ignored on `/v1/console/*`.
- **The public demo seeds `@ops` with PIN `2580`** (override with `DEMO_STAFF_HANDLE` / `DEMO_STAFF_PIN`; an empty PIN skips the seed). The PIN is documented because the demo is open. Rate limits apply (`console-sign-in`, 20 per 10 minutes per IP).
- **HTTP cannot mint.** Console routes read users, journal entries, the latest recon run, suspense items, the DLQ, and the audit log. The only write is replaying a *dead* outbox job, which retries a rail call and does not credit a wallet. Apply, refund, reverse, and journal post stay off this API (ADR 006, 016, 017).
- **Every signed-in action writes `staff_audit_events`.** Rows are append-only. Maker-checker on suspense and reversals still waits for staff ids on those services; this ADR only gives them a real session to hang off later.

## Consequences

- A reviewer can sign in at `/console/` without becoming `@amina`.
- Anyone who knows the documented demo PIN can read PII (phone, balances) on the public demo. That matches the open-demo contract; a licensed product would add TOTP (M5) and not publish the PIN.
- CLI actor strings remain until reversals and suspense take `staff_user_id`.
- CSRF tokens still wait for M5, same as wallet sessions.

## Alternatives considered

- **Reuse `users` with a role column.** A visitor who registered `@ops` would collide, and a stolen wallet session would open the console.
- **OTP through the sandbox inbox.** Mixes staff secrets into a public inbox.
- **HTTP apply/refund/reverse in this slice.** That is minting (or un-minting) from the open demo. Keep it on the CLI until maker-checker uses staff ids.
