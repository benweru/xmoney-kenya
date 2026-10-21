# Critiques

Short, blunt reviews of this project, written the way a senior fintech engineer would review it before an interview. Honest beats flattering.

## When

- At the end of every milestone: `mN.md`, or a range such as `m0-m1.md`.
- When a PR lands that changes how money moves (the ledger, payments, transfers, the worker, or the reconciler): add a short section to the current milestone's file. Docs-only and tooling PRs do not need one.

## Format

Keep it to about one page. Read the code, not just the PR descriptions.

1. **Scope**: the PRs and commit SHA reviewed.
2. **Ordinary**: what any competent CRUD project has. Name it so it is not oversold.
3. **Genuinely impressive**: what most portfolio projects do not have. Link to the code and the test.
4. **Weakest parts**: what a senior fintech engineer would poke at first. Rank them, and give a file and function for each. Say what goes wrong, in shillings or requests, not adjectives.
5. **What would raise the bar next**: at most three concrete changes, each small enough for one PR.
6. **Fed into the plan**: the top finding and where it went in the [roadmap](../roadmap.md). Every critique must change the plan, or say why it does not.

## Index

| File | Scope | Top finding | Roadmap item |
| --- | --- | --- | --- |
| [m0-m1.md](m0-m1.md) | PRs #1–#8 | A success callback with the right URL token credits a wallet with no second check | M2 critique follow-up |
| [m2-stk-query-confirm.md](m2-stk-query-confirm.md) | STK Query before credit | A failure callback with the URL token can still fail a paid top-up | Confirm failures with STK Query (M5 allowlist also helps) |
| [m3-hot-row.md](m3-hot-row.md) | First M3 slice: no float lock | Reconciler does not yet check running totals vs `SUM(postings)` | M3 reconciler |
| [m3-fees.md](m3-fees.md) | P2P fee schedules | Quote endpoint does not lock; UI can show a stale free allowance | Acceptable for demo; cash-out fees later |
| [m3-recon.md](m3-recon.md) | First reconciler | No settlement file, so paid-but-never-called-back is invisible | Mock settlement / Transaction Status |
| [m3-suspense.md](m3-suspense.md) | Suspense CLI | No staff identity; opening always hits the float | Console / maker-checker |
| [m3-reversals.md](m3-reversals.md) | Reversal CLI | Actor names are labels, not sessions | Console staff login |
| [m3-console.md](m3-console.md) | Staff console v1 | Published demo PIN; GET audits are noisy | M5 TOTP; staff ids on reverse/suspense |
| [m3-console-money.md](m3-console-money.md) | HTTP apply/refund/reverse | Recon still nags after suspense closes | Recon↔suspense glue |
| [m3-recon-suspense.md](m3-recon-suspense.md) | Quiet recon after suspense close | Staff still paste a break id | Mock settlement / console open-from-break |
| [m3-settlement.md](m3-settlement.md) | Mock settlement / Transaction Status | Sandbox still has no extract | Chaos evidence |
