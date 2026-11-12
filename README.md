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

When a task fails, the job goes back to `pending` and is retried after 5 s
(queue `jobs.retry`: message TTL, then dead-lettered back to `jobs`), up to 3
attempts in total. After the last attempt, or on a permanent failure (unknown
task), the job is `failed` and a message is published to the dead-letter
queue `jobs.dead`. The API exposes `attempts` and `last_error`.

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
- Retries with a fixed delay and a dead-letter queue (3 attempts, then `jobs.dead`)
- Graceful worker shutdown: on SIGTERM the worker finishes its current job, then stops
- Database schema managed with Alembic migrations
- Automated tests (pytest) against a real PostgreSQL database, and linting (ruff)
- Docker image shared by the API and the worker, built and smoke-tested in CI
- Docker Compose stack: PostgreSQL, RabbitMQ, one-shot migration job, API and worker
- Kubernetes manifests for a local Kind cluster (StatefulSets, migration Job, API and
  worker Deployments with probes and resource limits), checked by the same end-to-end tests
- Kubernetes end-to-end test in CI: a Kind cluster is created on the runner, the
  manifests are deployed and the integration tests run through `kubectl port-forward`
- Horizontal Pod Autoscaler on the API (CPU, 2 to 4 replicas) fed by metrics-server
- End-to-end integration tests in CI: the Compose stack is started and jobs are
  submitted through the API (success, retries, dead-letter queue, cancellation)
- GitHub Actions CI on pull requests and pushes to `main`

Planned: Helm, Prometheus, Grafana,
an admin CLI.

## Known limitations

- Tasks are simulated: `report-generation` waits for `payload.seconds`
  (default 2, capped at 30), `fail` always fails and `flaky` fails
  `payload.fail_times` times (default 1) before succeeding.
- The retry delay is fixed (5 s, set by the queue arguments): no exponential
  backoff. Nothing consumes `jobs.dead` yet: messages are kept for inspection.
- If a worker is killed while running a job, the job stays `running`
  (no timeout or recovery yet).
- The job is saved first, then published: a crash between the two leaves a
  `pending` job that is never queued.
- Kubernetes: the databases are single replicas, the worker has no probe and
  only the API is autoscaled. Kind announces that hosts using cgroup v1 will
  not be supported in a future release.

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

## Integration tests

They run against the real Compose stack and are not part of the default run:

    docker compose up -d --build
    cd services/api
    source ../../scripts/dev-env.sh
    python -m pytest integration_tests -v
    docker compose down

## Kubernetes (Kind)

The same application runs on a local Kind cluster (manifests in `deploy/k8s`):
PostgreSQL and RabbitMQ (StatefulSets with persistent volumes), a migration Job,
the API (2 replicas, rolling updates, probes) and the worker (graceful shutdown).
All containers have resource requests and limits, and the application containers
run as non-root.

Prerequisites: Docker, `kind` v0.33.0 and `kubectl` 1.34. Kubernetes 1.35 and newer
refuse to start on hosts using cgroup v1, so the cluster uses a pinned 1.34 node
image (see `scripts/kind-create.sh`).

    bash scripts/install-k8s-tools.sh   # kubectl 1.34 and kind v0.33.0, with checksums
    bash scripts/kind-create.sh
    bash scripts/k8s-deploy.sh    # builds the image, loads it into Kind, deploys
    bash scripts/k8s-e2e.sh       # integration tests through kubectl port-forward
    kind delete cluster --name cloudops

Secrets are created from the git-ignored `.env` file by `scripts/k8s-secrets.sh`:
nothing sensitive is committed.

Three scripts measure the behaviour of the cluster:

- `scripts/k8s-rollout-test.sh` sends requests to the API through its Service while
  a rolling update runs and counts the failed requests. The API containers have a
  5 s `preStop` hook so that the Service has time to stop routing to a pod before
  it stops accepting connections.
- `scripts/k8s-scale-demo.sh` compares the time needed to process 12 jobs with 1
  worker and with 3 workers (the workers are competing consumers of one queue).
- `scripts/k8s-hpa-demo.sh` installs metrics-server (v0.9.1, with
  `--kubelet-insecure-tls`, for a local Kind cluster only), creates the HPA of the
  API and generates load from inside the cluster while printing the autoscaler's
  decisions. The HPA target is 50 % of the CPU *request* (50m) of each pod. On a
  slow connection the installation can take several minutes, because the image is
  pulled by two pods created one after the other (the manifest, then its patch).

Measurements on a single-node Kind cluster (small samples, not guarantees):

| Scenario | Result |
|---|---|
| Rolling update of the API, no `preStop` | 3 failed requests out of 1110 |
| Rolling update of the API, with `preStop` | 0 failed out of 1150, and 0 out of 1151 (two runs) |
| 12 jobs of 3 s, 1 worker | 36.5 s |
| 12 jobs of 3 s, 3 workers | 12.6 s (4 jobs per worker) |
| API under load (about 2,400 requests/s for 150 s) | 2 to 4 replicas within about 30 s, 0 failed out of 361,259 requests |
| After the load stops | back to 2 replicas after about 2 minutes (60 s stabilization window) |
