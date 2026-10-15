# Sandbox-only API image. SANDBOX_MODE must stay true; the app refuses to start otherwise.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SANDBOX_MODE=true

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --system --uid 10001 xmoney
USER xmoney

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn xmoney.main:app --host 0.0.0.0 --port 8000"]
