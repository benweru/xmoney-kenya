# Daraja sandbox credentials (xMoney Kenya)

How to get Safaricom **sandbox** keys and where they go in this repo. The deployed demo stays on the **mock** rail until `enable_sandbox_rail` is true in app Terraform vars. Do not turn that on from this doc.

This build talks only to `https://sandbox.safaricom.co.ke`. It refuses production hosts such as `api.safaricom.co.ke`.

Never put consumer keys, secrets, or passkeys in git, chat, tickets, or screenshots.

## What you need

- Account at [developer.safaricom.co.ke](https://developer.safaricom.co.ke)
- An app with the **M-Pesa Express (Lipa Na M-Pesa Online)** sandbox product
- AWS CLI profile `xmoney`, region `eu-west-1` (only if you write Secrets Manager)
- Optional: a public **https** URL for callbacks (tunnel locally, CloudFront on AWS)

## 1. Register and copy four values

1. Sign in at [developer.safaricom.co.ke](https://developer.safaricom.co.ke) and create (or open) a sandbox app.
2. Attach **M-Pesa Express (Lipa Na M-Pesa Online)** for the sandbox environment.
3. Copy **Consumer Key** and **Consumer Secret** from the app page.
4. Copy the sandbox **shortcode** and **Lipa Na M-Pesa Online Passkey** from the portal’s M-Pesa Express test credentials. The shortcode is almost always `174379`.

Those four JSON keys are the only secrets this API uses:

| Key | Typical value |
| --- | --- |
| `DARAJA_CONSUMER_KEY` | from the app |
| `DARAJA_CONSUMER_SECRET` | from the app |
| `DARAJA_SHORTCODE` | `174379` |
| `DARAJA_PASSKEY` | from test credentials |

## 2. Callback URL

Daraja posts results to:

`$PUBLIC_BASE_URL/v1/payments/stk/callback/$STK_CALLBACK_TOKEN`

- Must be **public https**. `http://localhost` is not a valid CallBackURL.
- Locally: a tunnel (`cloudflared tunnel --url http://localhost:8000` or `ngrok http 8000`), then set `PUBLIC_BASE_URL` to that https origin.
- On AWS: CloudFront `PUBLIC_BASE_URL` is already public https.
- If you have no public URL, omit / unset the tunnel and rely on **STK Query**. The wallet is still only credited after query confirms, not from the callback alone.

Register that same https callback in the Daraja app if the portal asks for one. Do not invent extra portal screens; the four keys plus this URL are what the API needs.

## 3. Where to put the keys

### Laptop (`api/.env`)

`api/.env` is gitignored. Copy from `api/.env.example` if needed. Real values replace the placeholders (`sandbox`, `sandbox-passkey`). Those placeholders are refused when `"sandbox"` is in `PAYMENT_RAILS`.

```bash
PAYMENT_RAILS=["mock","sandbox"]
DARAJA_BASE_URL=https://sandbox.safaricom.co.ke
DARAJA_CONSUMER_KEY=<consumer key>
DARAJA_CONSUMER_SECRET=<consumer secret>
DARAJA_SHORTCODE=174379
DARAJA_PASSKEY=<passkey>
DARAJA_SANDBOX_ALLOWED_PHONES=["+2547XXXXXXXX"]
PUBLIC_BASE_URL=https://<your-tunnel-host>
STK_CALLBACK_TOKEN=<python3 -c "import secrets; print(secrets.token_hex(16))">
```

Check: `git status --short api/.env` prints nothing.

Details: [daraja-sandbox-top-up.md](daraja-sandbox-top-up.md).

### AWS Secrets Manager (deployed demo)

Secret name: `xmoney-demo/daraja-sandbox` (eu-west-1). Foundation already created it; it may be empty until you fill it.

The ECS task **does not** load this secret until `enable_sandbox_rail = true`. Filling the secret does not switch the demo off mock.

Write from a file so values stay out of shell history. Profile `xmoney`, region `eu-west-1`:

```bash
umask 077
# Edit /tmp/daraja.json with the four keys. Shortcode is usually 174379.
aws --profile xmoney --region eu-west-1 secretsmanager put-secret-value \
  --secret-id xmoney-demo/daraja-sandbox \
  --secret-string file:///tmp/daraja.json
rm -P /tmp/daraja.json 2>/dev/null || shred -u /tmp/daraja.json
```

Check: `describe-secret` shows `AWSCURRENT`. Never print the secret value.

Also set `sandbox_allowed_phones` in app tfvars when you enable the rail (real E.164 numbers you control). Sandbox prompts reach real handsets.

## 4. Sandbox lockdown (this backend)

- `SANDBOX_MODE` must stay true; the process will not start otherwise.
- `DARAJA_BASE_URL` must be exactly `https://sandbox.safaricom.co.ke`.
- Sandbox STK is limited to `DARAJA_SANDBOX_ALLOWED_PHONES` on a public https demo.
- Keep amounts at **KES 1** against the real sandbox.
- A success callback is **logged only**. Credit happens after **STK Query** confirms `CheckoutRequestID`.

## Gotchas

| Symptom | Likely cause |
| --- | --- |
| `Refusing to start: refusing Safaricom host` | `DARAJA_BASE_URL` is not the sandbox host |
| `the sandbox rail needs DARAJA_CONSUMER_KEY…` | placeholders still in `.env` while `PAYMENT_RAILS` includes `sandbox` |
| `rail_unavailable` | sandbox rail not offered, or phone not on the allowlist |
| Invalid Access Token / OAuth 400 | wrong consumer key/secret, or app missing M-Pesa Express |
| Wrong credentials | shortcode and passkey do not match |
| Invalid CallBackURL | `PUBLIC_BASE_URL` is not public https — tunnel it, or rely on STK Query |
| No prompt | phone not `+2547…` / `+2541…`, or line busy |
| Pending then expired | prompt ignored, or query rate-limited; a late callback can still credit after query |

## Related

- [daraja-sandbox-top-up.md](daraja-sandbox-top-up.md) — local sandbox STK
- [aws-first-deploy.md](aws-first-deploy.md) — Secrets Manager + `enable_sandbox_rail`
- [demo-payment-flow.md](demo-payment-flow.md) — first e2e payment
- [009-stk-query-before-credit.md](../adr/009-stk-query-before-credit.md)
