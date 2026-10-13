# Runbook: an STK top-up against the real Daraja sandbox

CI runs every top-up test against the local mock. This is the manual check that the same code works against Safaricom's **sandbox** (`sandbox.safaricom.co.ke`). The app refuses every other Safaricom host, so this cannot reach production.

## What you need

- A Daraja account at [developer.safaricom.co.ke](https://developer.safaricom.co.ke) with an app that has the **M-Pesa Express (Lipa Na M-Pesa Online)** sandbox product. The app page shows its **Consumer Key** and **Consumer Secret**.
- The sandbox **shortcode** and **passkey** from the portal's M-Pesa Express test credentials. The shortcode is usually `174379`.
- A phone on a Safaricom line you control. The sandbox sends a real STK prompt to it. Keep the amount at KES 1.
- Optional: a public https tunnel to your machine, such as `cloudflared tunnel --url http://localhost:8000` (no account needed) or `ngrok http 8000`. Without one, the callback cannot reach you, but STK Query still resolves the top-up after `STK_QUERY_AFTER_SECONDS`.

## Configure

Put the credentials in `api/.env`. That file is gitignored. Never commit it, and never paste the keys into an issue or PR.

```bash
DARAJA_BASE_URL=https://sandbox.safaricom.co.ke
DARAJA_CONSUMER_KEY=<consumer key>
DARAJA_CONSUMER_SECRET=<consumer secret>
DARAJA_SHORTCODE=174379
DARAJA_PASSKEY=<passkey from the portal>

# The tunnel's https URL, if you have one. Daraja will post to
# $PUBLIC_BASE_URL/v1/payments/stk/callback/$STK_CALLBACK_TOKEN
PUBLIC_BASE_URL=https://<your-tunnel-host>
STK_CALLBACK_TOKEN=<output of: python3 -c "import secrets; print(secrets.token_hex(16))">
```

Check before you run anything:

```bash
git status --short api/.env   # must print nothing: the file is ignored
```

## Run

```bash
make up && make migrate
make run                                  # terminal 1: the API, reading api/.env
cloudflared tunnel --url http://localhost:8000   # terminal 2, optional
make smoke-topup PHONE=+2547XXXXXXXX     # terminal 3
```

`make smoke-topup` registers `@smoketest` with that phone if it is new, signs in with the code from the sandbox inbox, sends a KES 1 STK Push, and polls `GET /v1/topups/{id}`. Approve the prompt on the phone. It prints each state and exits 0 only on `succeeded`:

```text
signed in as @smoketest
STK Push sent: ws_CO_... (pending)
  pending
  succeeded
final: succeeded result_code=0 receipt=... wallet=KES 1.00
```

With a tunnel, the callback usually lands within seconds and the receipt is set. Without one, the result comes from STK Query after about a minute, and the receipt stays empty. Both count.

## If it does not work

| Symptom | Likely cause |
| --- | --- |
| `Refusing to start: refusing Safaricom host` | `DARAJA_BASE_URL` is not exactly `https://sandbox.safaricom.co.ke`. |
| top-up `failed` with "Invalid Access Token" or a 400 from OAuth | wrong consumer key or secret, or the app lacks the M-Pesa Express product |
| top-up `failed` with "Wrong credentials" | shortcode and passkey do not match |
| top-up `failed` with "Invalid CallBackURL" | `PUBLIC_BASE_URL` is not a public URL. Use the tunnel's https URL, or remove the setting and rely on STK Query. |
| no prompt on the phone | the phone is not E.164 Safaricom (`+2547…` or `+2541…`), or the line is busy. Retry after a minute. |
| stays `pending`, then `expired` | the prompt was ignored, or STK Query is rate limited. A late callback still credits the wallet. |
| result code `1032` / `1037` / `1` | cancelled on the phone / phone unreachable / insufficient funds |

Afterwards, `GET /v1/accounts/{wallet}/balance` shows the credit, and `stk_callbacks` holds the raw callback. Record the date and the checkout id in the PR or release notes as evidence. Never record the credentials.
