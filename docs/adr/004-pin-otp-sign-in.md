# 004. Sign-in: hashed PIN, a one-time code, and server-side sessions

- Status: Accepted
- Date: 2026-10-13

## Context

M1 needs sign-in before money moves: a top-up or a send has to come from the wallet's owner. Kenyan mobile-money users already know a 4-digit PIN plus an SMS code. A PIN has at most a million values, so the hash alone cannot protect it; the defence is limiting guesses. The public demo cannot send SMS, and we want no third-party SMS account.

## Decision

- **PIN**: 4–6 digits, set at registration. Repeated digits and straight runs (`1111`, `1234`, `4321`) are refused. Stored only as an Argon2id hash (argon2-cffi defaults), rehashed on sign-in if the parameters change.
- **Lockout**: 5 wrong PINs in a row lock sign-in for 15 minutes. The credential row is locked (`SELECT … FOR UPDATE`) while it is checked and the count is committed before the error is returned, so parallel guesses are each counted. A correct PIN resets the count. Unknown phones get the same error and spend the same Argon2 time.
- **One-time code**: a correct PIN issues a 6-digit code that lives 5 minutes, allows 5 guesses, and works once. Only a SHA-256 of the code is stored. The code is "texted" to a **sandbox inbox** table, readable at `GET /v1/sandbox/inbox?phone=…`, in place of SMS.
- **Sessions**: a random 256-bit token in an `httpOnly`, `SameSite=Lax` cookie (`Secure` behind a setting so local http works). The database keeps only the token's SHA-256, with an expiry (12 hours) and a revoked time, so sign-out is immediate.

## Consequences

- Every money-moving route can depend on `current_user` and act only on the caller's wallet.
- The inbox shows any phone's codes to anyone. That is the point of an open sandbox demo and is unacceptable anywhere else; it refuses to run outside sandbox mode, and a real deployment would swap `deliver` for an SMS provider.
- A lockout lets anyone who knows a phone number block its sign-in for 15 minutes. Per-IP rate limits (M2) and step-up rules (M4) are the usual mitigations.
- `SameSite=Lax` blocks cross-site POSTs carrying the cookie in modern browsers, but explicit CSRF tokens wait for M5.

## Alternatives considered

- **JWTs**: stateless, but sign-out and lockout need a server-side list anyway. Opaque tokens are simpler to revoke and to explain.
- **bcrypt or PBKDF2**: fine, but Argon2id is the current OWASP recommendation and is memory-hard.
- **OTP only, no PIN**: a stolen or SIM-swapped phone would be enough to sign in. Two factors match what M-PESA users expect.
- **A real SMS provider** (Africa's Talking, Twilio): costs money per message and adds a secret to manage, for no extra signal in a sandbox.
