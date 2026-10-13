# Architecture decision records

Each ADR records one decision: the context, what we chose, and what it costs. ADRs are not edited after they are accepted. A changed decision gets a new ADR that supersedes the old one.

| ADR | Title | Status |
| --- | --- | --- |
| [001](001-stack-choice.md) | Stack: FastAPI and Postgres API, Next.js web app, one repo | Accepted |
| [002](002-ledger-design.md) | Ledger: double-entry, integer cents, balances derived from postings | Accepted |
| [003](003-aws-hosting-terraform-later.md) | Hosting on AWS, with Terraform added at the first deploy | Accepted |
| [004](004-pin-otp-sign-in.md) | Sign-in: hashed PIN, a one-time code, and server-side sessions | Accepted |

New ADRs copy [template.md](template.md) and take the next number.
