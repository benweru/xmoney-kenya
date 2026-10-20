# 016. Suspense: park unmatched value, then apply or refund

- Status: Accepted
- Date: 2026-10-20

## Context

[015](015-reconciliation.md) classifies breaks and does not move money. Unmatched inbound value still has to live somewhere until a person decides. `system:suspense` is already a credit-normal liability for "value we owe but cannot apply to a wallet yet." The public demo has no staff auth ([006](006-open-demo-protections.md)), so an HTTP mint-to-wallet would be a hole.

## Decision

**Opening** posts debit `system:mpesa_float`, credit `system:suspense`, and inserts a `suspense_items` row (`open`). Optional `recon_break_id`: at most one *open* item per break.

**Applying** posts debit suspense, credit the named wallet, and sets `applied`. **Refunding** posts debit suspense, credit float, and sets `refunded`. Both require a written reason. Corrections are new entries, never edits of the open posting.

**CLI only (`xmoney-suspense`).** No `/v1` route in this slice. Console staff auth can wrap the same service later.

## Consequences

- Opening without a real extra shilling at M-PESA still balances (float and liability rise together). That is a books decision, not cash appearing in a customer wallet.
- Applying to a handle is a deliberate credit. Keep it off the open demo HTTP surface.
- Maker-checker for large reversals is not this PR.

## Alternatives considered

- **Auto-open from every recon break.** Would park noise (running-balance drift is not inbound cash).
- **HTTP now, hide the route.** A crawler would still find it on the public demo.
