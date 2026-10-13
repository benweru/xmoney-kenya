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
