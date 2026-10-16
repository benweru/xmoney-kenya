# Hygiene

Checkable numbers for PR size and test coverage. CI time stays a README note until it is measured on `main`.

| Field | Value |
| --- | --- |
| Date | 15 Oct 2026 |
| Environment | GitHub Actions `api` job (coverage); `gh pr list` for PR size |
| Git SHA | this PR (`ledger-proof`) |
| Commands | see each section |

## Coverage (M1 core)

Command (what CI runs):

```bash
cd api && pytest --cov=xmoney --cov-report=term-missing --cov-fail-under=80
```

Targets from the [roadmap](../roadmap.md): at least **90%** line coverage on `ledger/`, `transfers/`, and `payments/topups.py`, and at least **80%** overall.

| Module | Target | Published |
| --- | --- | --- |
| `xmoney/ledger/` | ≥ 90% | measured in the `api` job log on this PR; job fails the repo if overall &lt; 80% |
| `xmoney/transfers/` | ≥ 90% | same |
| `xmoney/payments/topups.py` | ≥ 90% | same |
| `xmoney` overall | ≥ 80% | **enforced** (`--cov-fail-under=80`) |

Hypothesis properties in `tests/test_ledger_properties.py` exercise random top-ups, sends, refusals, and replays; they are included in that coverage run.

After this PR is green, copy the three module percentages from the job log into the table (honest numbers, including misses). Do not invent a figure that CI did not print.

## PR size (M0 core)

Target: median PR under 400 changed lines, excluding lockfiles.

```bash
gh pr list --state all --limit 50 --json additions,deletions,files,number,title
```

Status: **planned** until someone runs that command against `main` and pastes the median here. This PR is evidence docs plus tests; lockfiles are not in play.

## CI time (M0 core)

Target: the `api` job finishes in under 5 minutes on `main`. Read the Actions timing on the merge commit; do not guess from a laptop.
