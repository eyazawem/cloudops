# CloudOps

[![CI](https://github.com/eyazawem/cloudops/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/eyazawem/cloudops/actions/workflows/ci.yml)

Distributed job orchestration platform built to learn and demonstrate
DevOps practices: REST API, message queue, workers, containers,
Kubernetes and CI/CD.

## Architecture

    client -> API (FastAPI) -> PostgreSQL            1. job saved as "pending"
                  |
                  +---------> RabbitMQ               2. job id published to queue "jobs"
                                 |
                                 v
                              worker -> PostgreSQL   3. status: running, then succeeded or failed

Job lifecycle: `pending -> running -> succeeded | failed`. A pending job can
be cancelled through the API (`cancelled`). If the queue is unavailable when a
job is submitted, the job is marked `failed` and the API answers `503`.

Every status change is an atomic `UPDATE ... WHERE status = <expected>`, so a
cancelled job is never executed and a job is never started twice.

The API and the worker share one Docker image and one code base
(`services/api`); the worker runs `python -m app.worker`.

## Status

Under construction.

Implemented:
- FastAPI application with a `/health` endpoint
- Job endpoints: create, list, get and cancel, persisted in PostgreSQL
- Asynchronous processing: the API publishes each job to a durable RabbitMQ queue, a worker executes it and updates its status
- Database schema managed with Alembic migrations
- Automated tests (pytest) against a real PostgreSQL database, and linting (ruff)
- Docker image shared by the API and the worker, built and smoke-tested in CI
- Docker Compose stack: PostgreSQL, RabbitMQ, one-shot migration job, API and worker
- GitHub Actions CI on pull requests and pushes to `main`

Planned: retries and dead-letter queue, graceful worker shutdown, Kubernetes,
Helm, Prometheus, Grafana, an admin CLI.

## Known limitations

- Tasks are simulated: `report-generation` waits for `payload.seconds`
  (default 2, capped at 30) and `fail` always fails.
- No automatic retry. If a worker crashes while running a job, the job stays
  `running`.
- The job is saved first, then published: a crash between the two leaves a
  `pending` job that is never queued.
- The worker does not handle SIGTERM gracefully yet.

## Run everything with Docker Compose

    cp .env.example .env    # then replace the passwords in .env
    docker compose up -d --build

    curl -X POST http://127.0.0.1:8000/jobs \
      -H "Content-Type: application/json" \
      -d '{"task":"report-generation","payload":{"seconds":2}}'
    curl http://127.0.0.1:8000/jobs

    docker compose logs worker
    docker compose down     # data is kept in Docker volumes

The RabbitMQ management interface is available on http://127.0.0.1:15672
(credentials from `.env`).

## Local development

Prerequisites: Docker with Compose, Python 3.12.

Database and queue:

    cp .env.example .env    # then replace the passwords in .env
    docker compose up -d --wait db rabbitmq
    docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE ${POSTGRES_DB}_test;"'

API and worker:

    cd services/api
    python3.12 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements-dev.txt
    source ../../scripts/dev-env.sh    # exports DATABASE_URL, TEST_DATABASE_URL, RABBITMQ_URL
    alembic upgrade head
    uvicorn app.main:app --reload      # terminal 1
    python -m app.worker               # terminal 2

## Run tests and lint

The tests need `TEST_DATABASE_URL`, pointing to a database whose name ends
with `_test` (they refuse to run otherwise). RabbitMQ is replaced by a fake
publisher in the API tests.

    cd services/api
    source ../../scripts/dev-env.sh
    python -m pytest -v
    ruff check .
