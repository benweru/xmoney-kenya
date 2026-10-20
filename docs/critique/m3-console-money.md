# Critique: console apply / refund / reverse

**Scope**: Staff-session HTTP for suspense apply/refund and reversal propose/approve/reject, gated by `CONSOLE_MONEY_MOVING_ENABLED` (ADR 019). Written 21 Oct 2026.

## Ordinary

Ops buttons that post what the CLI already posted. Maker-checker as two logins.

## Genuinely impressive

- The same public-https refusal as the sandbox journal flag: the process will not start if money-moving writes would be on behind `https://` (`config.py` `refuse_real_money`).
- Maker and checker are the cookie's staff handle. Extra `maker` on the body is 422; the maker cannot approve themselves (`console/routes.py`, `test_console.py`).
- There is still no general journal-posting console route (ADR 006).

## Weakest parts, ranked

1. **Published PIN plus local minting.** On a laptop the default flag is on, so `@ops` / `2580` can credit a wallet. That is intended for `make demo`; it is not a control, only a deployment split (`DEFAULT_STAFF_PIN`).
2. **CSRF still open.** Cookie writes have no token (M5). Same as DLQ replay.
3. **Recon still nags after a close.** Applying or refunding does not quiet the linked recon break (`suspense/service.py`). The next run reports the same unmatched callback.

## What would raise the bar next

1. Mark a recon break quiet when its suspense item closes (recon-suspense glue).
2. Staff TOTP so the published PIN is not enough (already M5).
3. Seed a second local staff user so a reviewer can click maker-checker without inserting a row.

## Fed into the plan

Finding 3 is the next slice toward checkpoint 2. Finding 1 stays: public https keeps the flag off; the demo PIN stays published.
