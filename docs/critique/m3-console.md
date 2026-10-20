# Critique: staff console v1

**Scope**: Separate staff session, read-only console HTTP, DLQ replay, `/console` UI (ADR 018). Written 20 Oct 2026.

## Ordinary

A second login cookie and a CRUD-shaped ops UI. Every fintech has an admin.

## Genuinely impressive

- Wallet sessions cannot open `/v1/console/*`; staff have no wallet and no inbox OTP.
- Apply, refund, reverse, and journal post are still absent from HTTP, so the open demo still cannot mint.
- Lookups and DLQ replay write an append-only audit row.

## Weakest parts, ranked

1. **Published demo PIN.** `@ops` / `2580` is in the README. Anyone can read phones and balances on a live demo (`console/service.py` `DEFAULT_STAFF_PIN`).
2. **GET fan-out audits.** Every recon or DLQ list writes a row (`console/routes.py`). A polling tab fills the log; there is no sampling.
3. **Reversals and suspense still take CLI strings.** The session exists; maker-checker does not use `staff_user_id` yet.

## What would raise the bar next

1. Pass `StaffActor` into reverse/approve and suspense apply, and drop free-text `--maker`.
2. TOTP for staff (already M5).
3. Mark a recon break quiet when its suspense item closes (recon-suspense glue).

## Fed into the plan

Finding 1 is accepted for an open sandbox; M5 TOTP is the mitigation. Finding 3 is the next money-moving console slice, not this PR.
