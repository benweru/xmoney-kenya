# First e2e demo payment (this backend)

One STK top-up from the xMoney API/wallet, through the **mock** (default) or the **Daraja sandbox** rail. Credit happens only after **STK Query** confirms. A success callback is recorded; it does not mint money by itself.

No secrets in this file.

## What happens

1. Signed-in user: `POST /v1/topups` with `Idempotency-Key` and `amount_cents` (whole shillings, so a multiple of 100). Optional `"rail": "mock"` or `"sandbox"`. Optional `phone` if not using the account phone.
2. API sends Lipa Na M-Pesa Online (STK Push) on that rail. Response is `pending` with a `CheckoutRequestID`.
3. Phone shows an M-PESA PIN prompt (mock: simulated; sandbox: real Safaricom prompt).
4. Daraja may POST to `/v1/payments/stk/callback/{token}`. That is logged (`recorded`). Wallet **not** credited yet.
5. API calls **STK Query** for that `CheckoutRequestID` (right after a success callback, on `GET /v1/topups/{id}` after ~60s, and on the resolve-topups sweep).
6. Query says paid (`ResultCode 0`) → status `succeeded`, ledger credit (`system:mpesa_float` → wallet). Query says cancelled / timeout / no funds → `failed`. No answer by ~300s → `expired` (a later paid query/callback can still credit).

Poll `GET /v1/topups/{id}` and `GET /v1/me/balance`. Do not treat the callback as success.

## Mock path (always on; no Daraja keys)

Default `PAYMENT_RAILS=["mock"]`. Demo on AWS stays here until `enable_sandbox_rail` is true.

Last three digits of the MSISDN pick the outcome:

| Suffix | Result |
| --- | --- |
| `000` | success |
| `032` | cancelled (1032) |
| `037` | timeout / unreachable (1037) |
| `001` | insufficient funds (1) |
| `099` | push accepted, callback dropped (query still resolves) |

Receipts look like `SBOX…` so they are not live M-PESA.

### Quick success

```bash
make up && make migrate && make run
# other terminal: make run-web  — or use curl from README
make smoke-topup PHONE=+254712345000
```

Register a user whose phone ends in `000` (README uses `+254712345678` for general sign-in; for a guaranteed mock success use `…000`). Sign in (PIN, then sandbox inbox OTP). Top up, e.g. `{"amount_cents":50000}` (KES 500). Under the mock, STK Query is instant.

Expect: prompt “succeeds”, top-up `succeeded`, balance up by the amount, receipt `SBOX…`.

### Cancel check

Same flow with a phone ending `032`. Expect `failed`, result 1032, **no** wallet credit.

## Sandbox path (real prompt; sandbox host only)

Only after keys are in `api/.env` (laptop) or secret `xmoney-demo/daraja-sandbox` **and** `enable_sandbox_rail` (AWS). See [daraja-sandbox-setup.md](daraja-sandbox-setup.md). Host is only `sandbox.safaricom.co.ke`. Shortcode is usually `174379`. Keep amount **KES 1**.

```bash
make smoke-topup PHONE=+2547XXXXXXXX RAIL=sandbox
```

Or wallet UI: **Mock / Daraja sandbox** switch. Phone must be on `DARAJA_SANDBOX_ALLOWED_PHONES`. Use a Safaricom line you control (`+2547…` or `+2541…`). Portal test numbers are listed on [developer.safaricom.co.ke](https://developer.safaricom.co.ke) docs if you do not use your own SIM.

On the handset: M-PESA STK, PIN, then a sandbox confirmation (not live money).

- With a public https callback: callback usually arrives in seconds; receipt may be set; credit still waits for STK Query.
- Without a tunnel: wait ~`STK_QUERY_AFTER_SECONDS` (60). Receipt may stay empty. Both count if status is `succeeded` and balance moved.

## Verify

- `GET /v1/topups/{id}` → `succeeded` (or `failed` for 032 / cancel)
- `GET /v1/me/balance` matches the credit (or unchanged on fail)
- Callback row in `stk_callbacks` if one arrived; credit still required query confirm
- Never log consumer key/secret/passkey

## Success-path checklist

- [ ] API up (`make run` or demo URL); signed in
- [ ] Mock: phone ends `000`; or sandbox: allowlisted Safaricom phone, KES 1, rail `sandbox`
- [ ] `POST /v1/topups` with `Idempotency-Key` → `pending`
- [ ] Approve (mock auto / real PIN on sandbox)
- [ ] Poll until `succeeded` (query, not callback alone)
- [ ] Balance increased; mock receipt `SBOX…` if mock
- [ ] Replay same idempotency key → same top-up, no double credit

## Related

- [daraja-sandbox-setup.md](daraja-sandbox-setup.md)
- [daraja-sandbox-top-up.md](daraja-sandbox-top-up.md)
- [005-stk-topup-state-machine.md](../adr/005-stk-topup-state-machine.md)
- [009-stk-query-before-credit.md](../adr/009-stk-query-before-credit.md)
