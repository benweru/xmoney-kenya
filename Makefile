.PHONY: setup setup-api setup-web up demo down migrate migrate-check test test-api test-web \
	run run-web lint lint-api lint-web fmt pre-commit

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

# Postgres, the API (which serves the Daraja mock), and the web app, all in containers.
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

run-web:
	$(WEB) npm run dev

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
