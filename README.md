# CloudOps

[![CI](https://github.com/eyazawem/cloudops/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/eyazawem/cloudops/actions/workflows/ci.yml)

Distributed job orchestration platform built to learn and demonstrate
DevOps practices: REST API, message queue, workers, containers,
Kubernetes and CI/CD.

## Status

Under construction.

Implemented:
- FastAPI skeleton with a `/health` endpoint
- Automated tests (pytest) and linting (ruff)
- GitHub Actions CI on pull requests and pushes to `main`

Planned stack: Python, FastAPI, PostgreSQL, RabbitMQ, Docker, Kubernetes,
Helm, GitHub Actions, Prometheus, Grafana.

## Run the API locally

    cd services/api
    python3.12 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    uvicorn app.main:app --reload

Health check:

    curl http://127.0.0.1:8000/health

## Run tests and lint

    cd services/api
    python -m pytest -v
    ruff check .
