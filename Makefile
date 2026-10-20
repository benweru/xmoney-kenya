.PHONY: setup setup-api setup-web up demo down migrate migrate-check test test-api test-web \
	run run-web lint lint-api lint-web fmt pre-commit smoke-topup resolve-topups outbox-worker \
	openapi e2e screenshots demo-seed demo-reset \
	tf-check aws-bootstrap aws-foundation aws-plan aws-up aws-sleep aws-wake aws-down aws-run-job

# API commands run inside api/ with its own virtualenv. Web commands run inside web/.
API := cd api &&
WEB := cd web &&
VENV := .venv/bin

DEV_DATABASE_URL := postgresql+psycopg://xmoney:xmoney@localhost:5432/xmoney
TEST_DATABASE_URL := postgresql+psycopg://xmoney:xmoney@localhost:5432/xmoney_test

setup: setup-api setup-web

setup-api:
	$(API) python3 -m venv .venv
	$(API) $(VENV)/python -m pip install --upgrade pip
	$(API) $(VENV)/python -m pip install -e ".[dev]"
	@test -f api/.env || cp api/.env.example api/.env
	@if [ -d .git ]; then api/$(VENV)/pre-commit install; fi

setup-web:
	$(WEB) npm ci

up:
	docker compose up -d postgres
	@echo "Waiting for Postgres..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do \
		docker compose exec -T postgres pg_isready -U xmoney -d xmoney >/dev/null 2>&1 && exit 0; \
		sleep 1; \
	done; \
	echo "Postgres did not become ready"; exit 1

# Postgres, the API (which serves the Daraja mock), the outbox worker, and the web app.
demo:
	docker compose --profile app up --build

down:
	docker compose --profile app down

migrate:
	$(API) DATABASE_URL=$(DEV_DATABASE_URL) $(VENV)/alembic upgrade head

migrate-check:
	$(API) DATABASE_URL=$(TEST_DATABASE_URL) $(VENV)/alembic upgrade head
	$(API) DATABASE_URL=$(TEST_DATABASE_URL) $(VENV)/alembic check
	$(API) DATABASE_URL=$(TEST_DATABASE_URL) $(VENV)/alembic downgrade base
	$(API) DATABASE_URL=$(TEST_DATABASE_URL) $(VENV)/alembic upgrade head

test: test-api test-web

test-api:
	$(API) DATABASE_URL=$(TEST_DATABASE_URL) $(VENV)/alembic upgrade head
	$(API) TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(VENV)/pytest

test-web:
	$(WEB) npm run typecheck
	$(WEB) npm run build

run:
	$(API) DATABASE_URL=$(DEV_DATABASE_URL) $(VENV)/uvicorn xmoney.main:app --reload \
		--app-dir src --host 0.0.0.0 --port 8000

# next dev on :3000 calls the API on :8000 directly, so api/.env needs CORS_ORIGINS (see .env.example).
run-web:
	$(WEB) npm run dev

# Regenerate api/openapi.json and the web app's typed client from it.
openapi:
	$(API) $(VENV)/python scripts/export_openapi.py
	$(WEB) npm run api:types

# Playwright against a running stack on the mock (`make demo` in another terminal).
e2e:
	$(WEB) npx playwright test

# README screenshots from a fresh `make demo` stack, into docs/images/.
screenshots:
	$(WEB) node scripts/screenshots.mjs

# One STK top-up through a running API (`make run`), on the mock or the Daraja sandbox.
# PHONE=+254712345000 succeeds on the mock. RAIL=sandbox uses the Daraja sandbox;
# see docs/runbooks/daraja-sandbox-top-up.md.
smoke-topup:
	@test -n "$(PHONE)" || (echo "usage: make smoke-topup PHONE=+2547XXXXXXXX [AMOUNT=1]"; exit 1)
	$(API) $(VENV)/python scripts/topup_smoke.py --phone "$(PHONE)" --amount $(or $(AMOUNT),1) \
		$(if $(RAIL),--rail $(RAIL))

# Demo wallets (@amina, @baraka, @wanjiku) with history, in the dev database.
demo-seed:
	$(API) DATABASE_URL=$(DEV_DATABASE_URL) $(VENV)/xmoney-demo seed

# What the public demo does nightly: delete every wallet and payment, then seed again.
demo-reset:
	$(API) DATABASE_URL=$(DEV_DATABASE_URL) $(VENV)/xmoney-demo reset --yes

# Check top-ups still waiting on M-PESA with STK Query, and expire stale cash-outs.
resolve-topups:
	$(API) DATABASE_URL=$(DEV_DATABASE_URL) $(VENV)/xmoney-resolve-topups

# Run the outbox worker (retries, backoff, dead-letter queue). Ctrl-C stops it after the current job.
outbox-worker:
	$(API) DATABASE_URL=$(DEV_DATABASE_URL) $(VENV)/xmoney-outbox-worker

lint: lint-api lint-web

lint-api:
	$(API) $(VENV)/ruff check src tests alembic
	$(API) $(VENV)/ruff format --check src tests alembic
	$(API) $(VENV)/mypy

lint-web:
	$(WEB) npm run lint
	$(WEB) npm run format:check

pre-commit:
	api/$(VENV)/pre-commit run --all-files

fmt:
	$(API) $(VENV)/ruff check --fix src tests alembic
	$(API) $(VENV)/ruff format src tests alembic
	$(WEB) npm run format

# ---- AWS (docs/runbooks/aws-first-deploy.md, docs/runbooks/aws-costs.md) ----
# These use your AWS CLI credentials (export AWS_PROFILE first). CI never applies.
TF := infra/terraform
TF_BACKEND := -backend-config=../backend.hcl
APP_VARS := $(if $(TAG),-var api_image_tag=$(TAG)) \
	$(if $(SNAPSHOT),-var restore_snapshot_identifier=$(SNAPSHOT))

# What CI runs: formatting, validation without a backend, and tflint.
tf-check:
	terraform -chdir=$(TF) fmt -check -recursive
	for stack in bootstrap foundation app; do \
		terraform -chdir=$(TF)/$$stack init -backend=false -input=false >/dev/null && \
		terraform -chdir=$(TF)/$$stack validate || exit 1; \
	done
	cd $(TF) && tflint --init --config "$$PWD/.tflint.hcl" >/dev/null && \
		tflint --recursive --config "$$PWD/.tflint.hcl"

aws-bootstrap:
	terraform -chdir=$(TF)/bootstrap init -input=false
	terraform -chdir=$(TF)/bootstrap apply

aws-foundation:
	terraform -chdir=$(TF)/foundation init -input=false $(TF_BACKEND)
	terraform -chdir=$(TF)/foundation apply

aws-plan:
	terraform -chdir=$(TF)/app init -input=false $(TF_BACKEND)
	terraform -chdir=$(TF)/app plan $(APP_VARS)

# Create or update the app stack, awake. TAG=<sha> pins the image; SNAPSHOT=<id> restores RDS.
aws-up:
	terraform -chdir=$(TF)/app init -input=false $(TF_BACKEND)
	terraform -chdir=$(TF)/app apply $(APP_VARS)

# API to 0 tasks, RDS stopped (AWS restarts it after 7 days), schedules paused. The ALB keeps billing.
aws-sleep:
	terraform -chdir=$(TF)/app init -input=false $(TF_BACKEND)
	terraform -chdir=$(TF)/app apply -var awake=false $(APP_VARS)

aws-wake:
	terraform -chdir=$(TF)/app init -input=false $(TF_BACKEND)
	terraform -chdir=$(TF)/app apply -var awake=true $(APP_VARS)

# Destroy the app stack after RDS's final snapshot. Foundation (ECR, Budgets, OIDC) stays.
aws-down:
	infra/scripts/aws-down.sh

# Run a scheduled job now. JOB=demo-reset also seeds a brand-new database.
aws-run-job:
	@test -n "$(JOB)" || (echo "usage: make aws-run-job JOB=demo-reset|resolve-topups"; exit 1)
	infra/scripts/aws-run-job.sh $(JOB)
