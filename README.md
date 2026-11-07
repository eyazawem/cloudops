# CloudOps

[![CI](https://github.com/eyazawem/cloudops/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/eyazawem/cloudops/actions/workflows/ci.yml)

Distributed job orchestration platform built to learn and demonstrate
DevOps practices: REST API, message queue, workers, containers,
Kubernetes and CI/CD.

## Status

Under construction.

Implemented:
- FastAPI application with a `/health` endpoint
- Job endpoints: create, list, get and cancel, persisted in PostgreSQL
- Database schema managed with Alembic migrations
- Automated tests (pytest) against a real PostgreSQL database, and linting (ruff)
- Docker image for the API, built and smoke-tested in CI
- Docker Compose setup for a local PostgreSQL
- GitHub Actions CI on pull requests and pushes to `main`

Planned: RabbitMQ and workers, Kubernetes, Helm, Prometheus, Grafana.

## Local development

Prerequisites: Docker with Compose, Python 3.12.

Database:

    cp .env.example .env    # then replace the password in .env
    docker compose up -d --wait
    docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE ${POSTGRES_DB}_test;"'

API:

    cd services/api
    python3.12 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements-dev.txt
    source ../../scripts/dev-env.sh    # exports DATABASE_URL and TEST_DATABASE_URL
    alembic upgrade head
    uvicorn app.main:app --reload

Health check:

    curl http://127.0.0.1:8000/health

Stop the database (data is kept in a Docker volume):

    docker compose down

## Run tests and lint

The tests need `TEST_DATABASE_URL`, pointing to a database whose name ends
with `_test` (they refuse to run otherwise).

    cd services/api
    source ../../scripts/dev-env.sh
    python -m pytest -v
    ruff check .

## Run the API image with Docker

    docker build -t cloudops-api:dev services/api
    docker run --rm -p 8000:8000 cloudops-api:dev
    curl http://127.0.0.1:8000/health

`/health` works without a database. The job endpoints need `DATABASE_URL`;
running the API together with PostgreSQL in Compose is not set up yet.
