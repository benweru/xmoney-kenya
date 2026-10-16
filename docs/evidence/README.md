# Evidence

Checkable proof for the claims in the README. Each write-up names the git SHA, the environment, the date, and the exact command, so anyone can re-run it. Misses are published along with hits.

The plan and the targets are in the [roadmap](../roadmap.md#proof-track). Status values are **planned**, **in progress**, and **published**.

| Evidence | Milestone | Core or stretch | Target | Published in | Status |
| --- | --- | --- | --- | --- | --- |
| CI time | M0 | Core | API job under 5 min | README | planned |
| ADR for every hard decision | M0 | Core | 001–005 indexed | [`../adr/README.md`](../adr/README.md) | in progress |
| PR size | M0 | Core | median under 400 changed lines | `hygiene.md` | planned |
| "Broke it on purpose" results | M1 | Core | every manual mutation check re-run and listed | `correctness.md` | published |
| Hypothesis ledger properties | M1 | Core | 3 or more properties, at least 200 examples each | `correctness.md` | published |
| Coverage per module | M1 | Core | at least 90% on ledger, transfers, and top-ups; at least 80% overall | README, `hygiene.md` | in progress |
| Mutation score (mutmut) | M1 | Stretch | at least 70% on the ledger, at least 60% on the others | `correctness.md` | planned |
| Load test, first row | M2 | Core | at least 30 sends/s, p95 under 300 ms, p99 under 800 ms, errors under 0.5%, drift 0 | README, `load-tests.md` | planned |
| Measured AWS cost | M2 | Core | at most $25 for a month awake, at most $3 with the app stack torn down | README, `cost.md` | planned |
| Dependency, container, and secret scans | M2 | Core | 0 high or critical findings open more than 7 days | README badges, `security-scans.md` | in progress |
| Lighthouse (mobile) | M2 | Stretch | performance at least 90, accessibility at least 95 | `web.md` | planned |
| Chaos suite with counts | M3 | Core | at least 1,000 faults, 0 unexplained, drift 0 | `chaos.md` | planned |
| Load test, second row | M3 | Core | at least 2× the M2 sends/s at the same p95 | `load-tests.md` | planned |
| Mutation score on the worker and reconciler | M3 | Core | as in M1 | `correctness.md` | planned |
| Chaos demo video or GIF | M3 | Stretch | 60 seconds | README | planned |
| RDS reboot recovery | M3 | Stretch | measured and published | `chaos.md` | planned |
| NPS Bill 2026 mapping | M4 | Core | 2 pages, cited clauses only | `nps-bill-2026.md` | planned |
| OWASP ASVS L1 checklist | M4 | Core | at least 90% of applicable items pass | `asvs.md` | planned |
| ASVS L2 (V2, V3) | M4 | Stretch | auth and session chapters | `asvs.md` | planned |
| SLOs and error budget | M5 | Core | 2 SLOs over a 28-day window | `slos.md` | planned |
| Dashboard and trace screenshots | M5 | Core | 1 dashboard, 1 end-to-end trace | README, this folder | planned |
| STRIDE threat model | M5 | Core | at least 20 threats with a mitigation and a test | [`../threat-model.md`](../threat-model.md) | planned |
| Postmortem of a real incident | M5 | Core | 1, blameless format | `postmortem-001.md` | planned |
| Load test, third row (tracing on) | M5 | Core | shows what tracing costs | `load-tests.md` | planned |
| Load test with 2 API tasks | M5 | Stretch | scaling and its cost | `load-tests.md` | planned |
| Webhook delivery under chaos | M6 | Stretch | 100% delivered or sent to the DLQ | `webhooks.md` | planned |
| Merchant API load with replays | M6 | Stretch | replays add 0 postings | `load-tests.md` | planned |
