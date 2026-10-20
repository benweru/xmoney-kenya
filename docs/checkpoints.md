# Checkpoints

Agents keep building between these. Catch Ben up only here: what landed, what is next, and the questions. Do not wake AWS unless a checkpoint decision needs it.

1. **M3 ops console on main** — Staff console v1: separate session, `/console` UI, user lookup, ledger explorer, recon, read-only suspense, DLQ replay, audit. No HTTP minting.
   - Demo staff PIN published vs env-only?
   - Apply/refund/reverse on HTTP with staff ids, or keep CLI?
2. **M3 money-correctness closed** — Recon↔suspense glue, mock settlement / Transaction Status, chaos evidence, M3 load-test row, mutation on worker/recon.
   - Tag M3, or more evidence first?
   - AWS wake for load, or local-only?
3. **M4 risk & compliance** — KYC tiers, rules engine, sanctions snapshot, case queue, DPA + NPS Bill 2026 write-up.
   - Where do limit numbers come from?
   - How deep is the case queue vs STR export?
4. **M5 production-readiness** — Staff TOTP, CSRF, OTEL/X-Ray, SLOs/dashboard, STRIDE, on-call runbook.
   - WAF on or off for cost?
   - Enable Multi-AZ even briefly?
5. **Portfolio close (M6 or skip)** — Merchant API / webhooks / Lipa QR, or skip M6 and tag the demo.
   - Do M6, or stop?
