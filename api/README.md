# X Money for Kenya: API

The FastAPI backend: double-entry ledger, @handle registry, and the `PaymentsProvider` seam with a local Daraja mock. Sandbox only. It refuses to start unless `SANDBOX_MODE=true` and refuses every Safaricom host except `sandbox.safaricom.co.ke`.

See the [repository README](../README.md) for the full description and the [ADRs](../docs/adr/) for design decisions.

```text
src/xmoney/ledger/      accounts, journal, postings, balances
src/xmoney/identity/    handles, E.164 phones, wallet creation
src/xmoney/auth/        PIN + one-time code sign-in, sessions
src/xmoney/inbox/       sandbox inbox (stands in for SMS)
src/xmoney/payments/    STK top-ups, PaymentsProvider, Daraja client, local mock
src/xmoney/transfers/   send to an @handle without overdrafts
alembic/                schema, triggers, and the seeded chart of accounts
scripts/                topup_smoke.py, for the mock or the Daraja sandbox
tests/                  ledger, concurrency, handles, auth, top-ups, sends, API, mock
```

Run commands from the repository root with `make` (`make setup`, `make test`, `make run`), or from this directory with the virtualenv in `api/.venv`.
