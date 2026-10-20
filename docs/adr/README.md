# Architecture decision records

Each ADR records one decision: the context, what we chose, and what it costs. ADRs are not edited after they are accepted. A changed decision gets a new ADR that supersedes the old one.

| ADR | Title | Status |
| --- | --- | --- |
| [001](001-stack-choice.md) | Stack: FastAPI and Postgres API, Next.js web app, one repo | Accepted |
| [002](002-ledger-design.md) | Ledger: double-entry, integer cents, balances derived from postings | Accepted |
| [003](003-aws-hosting-terraform-later.md) | Hosting on AWS, with Terraform added at the first deploy | Accepted |
| [004](004-pin-otp-sign-in.md) | Sign-in: hashed PIN, a one-time code, and server-side sessions | Accepted |
| [005](005-stk-topup-state-machine.md) | STK top-ups: a state machine with exactly-once callbacks | Accepted |
| [006](006-open-demo-protections.md) | Open demo protections: no minting route, and rate limits counted in Postgres | Accepted |
| [007](007-aws-iam-design.md) | AWS IAM: OIDC deploys, one role per job, and secrets per task | Accepted |
| [008](008-no-nat-gateway.md) | AWS network: no NAT gateway, tasks in public subnets, CloudFront in front | Accepted |
| [009](009-stk-query-before-credit.md) | Credit an STK top-up only after STK Query confirms | Accepted |
| [010](010-wallet-running-balance-no-float-lock.md) | Do not lock system accounts; running balances on wallets | Accepted |
| [011](011-transactional-outbox.md) | A Postgres transactional outbox with leases, backoff and a dead-letter queue | Accepted |
| [012](012-stk-push-via-outbox.md) | STK Push is sent by the outbox worker, not the API request | Accepted |
| [013](013-b2c-cashout.md) | B2C cash-out: hold, then settle or release | Accepted |
| [014](014-p2p-fee-engine.md) | P2P fee engine: versioned schedules, three-leg postings | Accepted |
| [015](015-reconciliation.md) | Reconciliation classifies breaks; it does not repair them yet | Accepted |
| [016](016-suspense.md) | Suspense: park unmatched value, then apply or refund | Accepted |

New ADRs copy [template.md](template.md) and take the next number.
