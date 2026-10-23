# Positioning: X Money for Kenya

**Audience:** Ben + Cursor agent (keep this true while building).  
**Status:** Product framing, not a licence claim. Sandbox only — see README.

## One sentence

**Main pillar:** show how a **social platform** can integrate a **local payment rail** (M-PESA in Kenya) into the product people already use — pay `@handle` in-app, top up from the phone wallet, keep the books honest.

This repo is that pattern as a Kenya sandbox (framed as what an X Money–style expansion would need). Rails already exist; we are not inventing a payment network.

## What we are *not* building

- We are **not** inventing mobile-money rails. Cross-border and domestic payouts **to M-PESA / local banks already ship** (e.g. [Eversend, Sep 2026](https://x.com/eversendapp/status/2097992149992079771): “send funds instantly to Kenya, Nigeria, Uganda… direct to mobile money or local bank accounts”). That post is **proof of work that the technology exists**.
- We are **not** announcing an X product. Frame every public line as *“what a Kenya expansion would need”*, never as an X Corp launch.
- We are **not** a licensed payment service. README and process must keep saying that.

## What we *are* proving

| Layer | Reality | Our job |
| --- | --- | --- |
| Rails | STK Push, B2C, Paybill, Daraja / PSPs | Integrate correctly (handshake, idempotency, recon) |
| Product | Remittance apps send to a **phone number** | Send to a **person you already follow** (`@handle`) |
| Market entry | Cards / GlobalPay need Visa + FX friction | Native STK / Paybill in **KES**, no card required |

**Differentiator (defend this in interviews):**  
Remittance apps move money to a phone number. X Money moves it to a person you already follow — tip a creator, pay for a post, split a bill in DMs — with M-PESA in (and out) and no card.

### Why not “just Visa / prepaid via M-PESA GlobalPay?”

That pushback is the real product work. Short answer:

1. **No card** — STK Push uses the phone’s M-PESA PIN; most Kenyans already have that, not a Visa.
2. **KES end-to-end** — no FX markup for local P2P and creator payouts.
3. **Paybill “Account” = @handle** — pay from the M-PESA menu without opening X first (design target).
4. **Social context** — payment sits where the conversation already is; GlobalPay does not.

Cash-out (B2C) is **lower priority** than M-PESA → wallet top-up and @handle P2P.

## Money rules (non-negotiable)

1. **Handshake** — one side is never credited unless the other side is debited. Wallet credit only after M-PESA confirms (**STK Query**, not the callback alone). Expired top-ups mean “we stopped waiting,” shown as a graceful failure — never a silent credit.
2. **Late approval** — if Safaricom confirms after our wait window, credit only with confirmation, and the UI must say the request timed out *then* that a late payment landed.
3. **Duplicate-send hard block** — same sender + same @handle + same amount within a configurable wait (default **3 minutes**; Safaricom publishes no official figure — label as our design) is **refused** in app *and* in the database. Different amount or recipient is allowed.
4. **Reconciliation** — expected when an external network can disagree with our books. Classify mismatches; repair only with new ledger entries (suspense / reversal), maker-checker for large fixes. Never “edit history.”

## Evidence to keep citing

- Eversend (and peers): rails to mobile money already exist → we package, we don’t invent.
- Our own proof track: chaos / load / mutation / live demo when those numbers exist — don’t claim them until they do.

## One-line panel defence

> “We’re not building a new payment rail. We’re showing how an @handle wallet on top of M-PESA would have to behave — handshake credits, duplicate guards, and recon — so a Kenya launch wouldn’t mint money or strand balances.”
