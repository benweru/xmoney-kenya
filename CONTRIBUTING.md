# Contributing

## Branch names

Name a branch after the broadest accurate label for what it builds, in kebab-case:

- Good: `dev-tooling`, `wallet-sign-in`, `stk-top-up`, `reconciliation`, `operations-console`.
- No tool or author prefixes such as `cursor/`, `feature/`, or `ben/`.
- No week or milestone numbers such as `week1-foundation` or `m3-outbox`. Milestones are tracked on issues and the project board, and a branch name should still make sense if the work moves to another milestone.

Prefer the broader label when in doubt: `dev-tooling` rather than `add-pre-commit`, as long as the name stays accurate for everything on the branch.

## Pull requests

`main` is protected. Every change lands through a pull request that needs one approval and green CI (`api`, `web`, `compose`, and `security` among the jobs).

- Keep PRs small, and describe what changed, why, and how it was tested.
- Link the issue it closes (`Closes #12`).
- Squash-merge so `main` reads as a list of features.
- Write imperative, specific commit messages ("Apply STK callback idempotently on CheckoutRequestID"), not "wip" or "fix stuff".

## Local checks

`make setup` creates `api/.venv`, installs `web/node_modules`, and installs the pre-commit hooks. Before pushing, run:

```bash
make lint
make test
make pre-commit
```

The hooks run ruff and mypy on `api/`, and ESLint and Prettier on `web/`. `make fmt` applies ruff and Prettier formatting.

## Cursor agent context

`.cursor/rules/` is intentional project context for Cursor agents; leave those files in the repo.

## Sandbox only

Nothing in this repository may move real money. Do not add production Safaricom hosts, real credentials, or a way to turn sandbox mode off.
