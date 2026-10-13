# 006. Open demo protections: no minting route, and rate limits counted in Postgres

- Status: Accepted
- Date: 2026-10-13

## Context

The public demo is fully open: no password, no invite. Anyone can register, sign in with a code from the sandbox inbox, top up through the mock, and send. Two things made that unsafe:

- `POST /v1/sandbox/journal-entries` took any balanced entry with no session, so one request could credit any wallet. It existed to show the ledger on a laptop.
- Nothing limited request rates. A script could register thousands of handles, guess codes from many phones, flood the mock with STK pushes, or poll hard enough to keep the database busy.

The architecture rule is one database, one API, one worker. The API runs as more than one Fargate task, so in-process counters would let a client multiply its limit by the task count.

## Decision

**The journal route is off unless `SANDBOX_JOURNAL_ENABLED=true`.** When it is off, the route answers `404 not_found`, the same as a route that does not exist. Settings refuse to load with the flag on when `PUBLIC_BASE_URL` is `https://`, so a deployed demo cannot turn it on by mistake. Tests turn it on only for the two tests that exercise it. The mock's `PUT /sandbox/daraja/__control/behavior`, which changes the outcome for every visitor, can be turned off with `DARAJA_MOCK_CONTROL_ENABLED=false`, and `TOPUP_MAX_CENTS` lowers the largest single top-up (it can never exceed the KES 250,000 hard cap).

**Rate limits are fixed-window counters in a Postgres table.** Each request upserts one row, `(bucket, window_start) → hits`, and is refused with `429 rate_limited` and `Retry-After` once `hits` passes the limit. The count commits before the endpoint runs, so a request that fails (a wrong PIN, a bad code) still counts. Buckets are `scope:sha256(identity)`, so the table never holds a raw IP or user id. Old windows are pruned on about 1% of requests.

| Limit | Per | Allowed |
| --- | --- | --- |
| Every `/v1` and `/sandbox` request | IP | 300 a minute |
| Register | IP | 10 an hour |
| Sign in (phone + PIN) | IP | 20 per 10 minutes |
| Verify a code | IP | 20 per 10 minutes |
| Read the sandbox inbox | IP | 60 a minute |
| Look up a handle | IP | 60 a minute |
| Start a top-up | user | 10 an hour |
| Send | user | 30 per 10 minutes |

`/health` is never limited, so load balancer checks cannot be throttled.

**Client IPs come from `X-Forwarded-For` only as far as trusted proxies wrote it.** With `TRUSTED_PROXY_HOPS=N`, the client is the Nth address from the right. On AWS, CloudFront appends the viewer and the ALB appends the CloudFront edge, so `N=2`. Anything to the left was written by the client and is ignored, so prepending a fake address does not get a fresh bucket. With `N=0` (the default) the header is ignored entirely.

## Consequences

- One upsert per limited request. At demo traffic that is negligible, and it is the same database every request already uses.
- A fixed window allows a burst of up to twice the limit across a window boundary. That is fine for abuse control; it would not be for billing.
- Visitors behind one NAT (a campus, a mobile carrier) share an IP bucket. The per-IP limits are set high enough for a classroom to try the demo at once.
- Per-PIN and per-code lockouts from ADR 004 still apply on top of these limits.
- M5 can add an AWS WAF rate-based rule at CloudFront, which drops floods before they reach the API.

## Alternatives considered

- **In-memory counters (for example `slowapi`).** Each Fargate task would count separately, and a restart would reset every limit.
- **Redis or ElastiCache.** The textbook choice for counters, but it is a second stateful service to pay for and run, and the rule is one database.
- **Sliding-window logs.** Exact, but one row per request instead of one per window.
- **Only AWS WAF.** It costs about $6+ a month, cannot see users (only IPs), and does nothing for `make demo` on a laptop.
- **Deleting the journal route.** It is still the quickest way to show the ledger's idempotency and conflict rules locally, so it stays, behind a flag that cannot be on in a deployment.
