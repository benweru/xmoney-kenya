.PHONY: setup up down migrate test run lint fmt

PY := .venv/bin/python
PIP := $(PY) -m pip
ALEMBIC := .venv/bin/alembic
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff
UVICORN := .venv/bin/uvicorn

export PYTHONPATH := src

DEV_DATABASE_URL := postgresql+psycopg://xmoney:xmoney@localhost:5432/xmoney
TEST_DATABASE_URL := postgresql+psycopg://xmoney:xmoney@localhost:5432/xmoney_test

setup:
	python3 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PIP) install -e ".[dev]"
	@test -f .env || cp .env.example .env

up:
	docker compose up -d
	@echo "Waiting for Postgres..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do \
		docker compose exec -T postgres pg_isready -U xmoney -d xmoney >/dev/null 2>&1 && exit 0; \
		sleep 1; \
	done; \
	echo "Postgres did not become ready"; exit 1

down:
	docker compose down

migrate:
	DATABASE_URL=$(DEV_DATABASE_URL) $(ALEMBIC) upgrade head

test:
	DATABASE_URL=$(TEST_DATABASE_URL) $(ALEMBIC) upgrade head
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PYTEST)

run:
	DATABASE_URL=$(DEV_DATABASE_URL) $(UVICORN) xmoney.main:app --reload --host 0.0.0.0 --port 8000

lint:
	$(RUFF) check src tests alembic
	$(RUFF) format --check src tests alembic

fmt:
	$(RUFF) check --fix src tests alembic
	$(RUFF) format src tests alembic
