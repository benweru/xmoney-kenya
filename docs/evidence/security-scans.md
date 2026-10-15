# Security scans

Dependency, container, and secret scans for milestone M2. Target: **zero high or critical findings** left unexplained (open more than 7 days without a listed reason).

| Field | Value |
| --- | --- |
| Date | 15 Oct 2026 |
| Environment | GitHub Actions `security` job on `ubuntu-latest` |
| Git SHA | this PR (`security-scans`); re-check the merge SHA on `main` |
| Commands | see below |

## What runs in CI

The `security` job in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) on every pull request and on `main`:

```bash
# API dependencies (installed extras match the pytest job)
cd api && pip install -e ".[dev]" pip-audit && pip-audit --progress-spinner off --desc on

# Web production dependencies only (dev tooling is omitted)
cd web && npm ci && npm audit --omit=dev --audit-level=high

# Git history, not only the working tree
gitleaks detect --source . --verbose --redact --exit-code 1

# Images the demo actually ships
docker compose --profile app build
trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 xmoney-kenya-api:latest
trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 xmoney-kenya-web:latest
```

`pip-audit` fails the job on any reported vulnerability. `npm audit --audit-level=high` fails on high or critical only (moderate and low are listed in the log). Trivy fails on high or critical issues **that have a fix**. Unfixed distro CVEs are published below when they appear, rather than blocking every PR on a base-image lag.

Gitleaks uses [`.gitleaks.toml`](../../.gitleaks.toml). Documented sandbox placeholders (`sandbox` Daraja keys, `curl -u sandbox:sandbox` in the README, local `xmoney:xmoney` compose passwords, test callback tokens) are allowlisted. Real secrets still fail CI. `api/.env` and `.sf/` are gitignored and must stay that way.

## Latest result (this write-up)

| Scanner | Scope | High | Critical | Unexplained |
| --- | --- | --- | --- | --- |
| pip-audit | `api` with `[dev]` | 0 (job fails otherwise) | 0 | none |
| npm audit --omit=dev | `web` production tree | 0 (job fails otherwise) | 0 | none |
| gitleaks | git history | n/a | n/a | none |
| Trivy | `xmoney-kenya-api`, `xmoney-kenya-web` | 0 with a fix | 0 with a fix | none |

Accepted findings: **none.** The API and web Dockerfiles run `apt-get upgrade` / `apk upgrade` at image build so high/critical issues that already have a distro fix are not left sitting on a stale base tag. If Trivy still fails, list the CVE here with a reason and a review date within 7 days instead of silencing the job.

## Local

Same commands as CI. Trivy and gitleaks need those CLIs (or the Docker images `aquasec/trivy` and `ghcr.io/gitleaks/gitleaks`). Do not scan `api/.env`.

## Honesty

This job adds a few minutes of student CI time because it builds the two demo images. It does not start the stack (the `compose` and `e2e` jobs still do that). pip-audit and npm audit are not folded into the pytest job so a red scan is obvious.

Badges on the README point here and at the CI workflow. They are not a live CVE count; the table above is.
