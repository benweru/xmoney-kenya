# Clear a suspense item

Sandbox-only. This does not move real money. There is no HTTP route; use the CLI against the database the API uses.

## When

`xmoney-recon` reported `missing_on_ledger` or `amount_mismatch`, and you have decided the shillings are ours to apply or to return to the float.

Do **not** open suspense for `running_balance_drift`. That is a books bug, not unmatched cash.

## Open

```bash
make suspense ARGS='open --cents 10000 --reason "unmatched STK receipt SBOXABCD"'
# optional: --break <recon_breaks.id>
```

That posts debit `system:mpesa_float` / credit `system:suspense` for KES 100.00.

## Apply to a wallet

The customer is identified; they should have the money.

```bash
make suspense ARGS='apply --id <item-uuid> --to amina --reason "customer emailed receipt"'
```

## Refund to the float

The collection should not sit as a customer liability.

```bash
make suspense ARGS='refund --id <item-uuid> --reason "return to Daraja sandbox"'
```

## List open items

```bash
make suspense ARGS=list
```

On AWS, use `make aws-run-job` only after a job definition exists for this CLI; until then, run `xmoney-suspense` in a one-off task the same way as `xmoney-recon`, or run it locally against a copy of the data. Prefer local compose while the demo is asleep.
