# 001. Stack: FastAPI and Postgres API, Next.js web app, one repo

- Status: Accepted
- Date: 2026-10-13

## Context

X Money for Kenya is a sandbox-only pay-by-@handle wallet. The interesting work is in money correctness: a ledger that cannot be unbalanced, payments that apply exactly once when M-PESA callbacks are lost or duplicated, and reconciliation. The week 1 foundation already uses FastAPI, SQLAlchemy 2, Alembic, pytest, and PostgreSQL 16, with a `PaymentsProvider` seam in front of a local Daraja mock.

The project also needs a wallet UI and a back-office console, and it is built by one person, so every extra service or language has to pay for itself.

## Decision

- **API**: keep Python 3.12, FastAPI, SQLAlchemy 2, Alembic, and PostgreSQL 16 in `api/`. Postgres is the only datastore. Ledger invariants are enforced in the database as well as the service ([ADR 002](002-ledger-design.md)).
- **Payments**: every rail sits behind `PaymentsProvider`. Tests and the demo use the local Daraja mock; the Daraja sandbox is a configuration change. The app refuses to start unless `SANDBOX_MODE=true` and refuses every Safaricom host except `sandbox.safaricom.co.ke`.
- **Background work**, when it arrives: a Python worker reading a Postgres outbox table with `FOR UPDATE SKIP LOCKED`, not a separate queue.
- **Web**: Next.js (App Router), TypeScript, and Tailwind in `web/`. The wallet and the staff console share one app; the console lives under `/console`. API types will be generated from FastAPI's OpenAPI schema.
- **Repo**: one monorepo with `api/`, `web/`, and `docs/`. One CI workflow runs a job per part, plus a docker compose smoke test.

## Consequences

- Two languages (Python and TypeScript), but each is the default choice for its job, and the OpenAPI contract keeps them in sync.
- One database and one API keep the failure modes few enough to reason about and test. A new service needs its own ADR.
- Moving `src/` and `tests/` into `api/` now is cheap; later it would touch every open branch.

## Alternatives considered

- **Rewrite the API in TypeScript (NestJS) to share one language.** Throws away working, tested code for little signal.
- **Django.** Its admin would give a console quickly, but the ORM and async story fit the existing SQLAlchemy/Alembic code worse, and the console is a deliberate showcase of authorization.
- **Kafka, Celery, or Redis queues.** Extra infrastructure to run and explain. A Postgres outbox gives retries and a dead-letter table with the transaction guarantees we already rely on.
- **Separate repos for API and web.** More overhead for one developer and no atomic changes across the API contract.
