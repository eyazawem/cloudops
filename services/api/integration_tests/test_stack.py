"""End-to-end tests against the running Docker Compose stack.

Start the stack first (docker compose up -d --build) and export the variables
of scripts/dev-env.sh. These tests are not part of the default test run.
"""

import json
import os
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from app.messaging import RETRY_DELAY_MS
from app.worker import MAX_ATTEMPTS

API_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
MANAGEMENT_URL = os.environ.get("RABBITMQ_MANAGEMENT_URL", "http://127.0.0.1:15672")
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "cloudops")

STARTUP_TIMEOUT = 90.0
JOB_TIMEOUT = 60.0
DEAD_LETTER_TIMEOUT = 15.0
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

Job = dict[str, Any]


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_URL, timeout=10) as http:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while True:
            try:
                if http.get("/health").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                pytest.fail(f"API not healthy after {STARTUP_TIMEOUT:.0f} s")
            time.sleep(1)
        yield http


def submit(client: httpx.Client, task: str, payload: dict | None = None) -> str:
    response = client.post("/jobs", json={"task": task, "payload": payload or {}})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def get_job(client: httpx.Client, job_id: str) -> Job:
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200, response.text
    return response.json()


def wait_for(
    client: httpx.Client,
    job_id: str,
    predicate: Callable[[Job], bool],
    description: str,
) -> Job:
    deadline = time.monotonic() + JOB_TIMEOUT
    while True:
        job = get_job(client, job_id)
        if predicate(job):
            return job
        if time.monotonic() > deadline:
            pytest.fail(f"timeout waiting for {description}; last state: {job}")
        time.sleep(0.25)


def wait_for_terminal_status(client: httpx.Client, job_id: str) -> Job:
    return wait_for(
        client,
        job_id,
        lambda job: job["status"] in TERMINAL_STATUSES,
        "a terminal status",
    )


def dead_letters() -> list[Job]:
    """Read the dead-letter queue through the RabbitMQ management API.

    Messages are requeued, so reading does not consume them.
    """
    response = httpx.post(
        f"{MANAGEMENT_URL}/api/queues/%2F/jobs.dead/get",
        json={"count": 100, "ackmode": "ack_requeue_true", "encoding": "auto"},
        auth=(RABBITMQ_USER, os.environ["RABBITMQ_PASSWORD"]),
        timeout=10,
    )
    response.raise_for_status()
    return [json.loads(message["payload"]) for message in response.json()]


def wait_for_dead_letter(job_id: str) -> Job:
    deadline = time.monotonic() + DEAD_LETTER_TIMEOUT
    while True:
        for message in dead_letters():
            if message["job_id"] == job_id:
                return message
        if time.monotonic() > deadline:
            pytest.fail(f"no dead-letter message for job {job_id}")
        time.sleep(0.5)


def test_job_succeeds_on_first_attempt(client):
    job_id = submit(client, "report-generation", {"seconds": 1})
    job = wait_for_terminal_status(client, job_id)
    assert job["status"] == "succeeded", job
    assert job["attempts"] == 1


def test_flaky_job_is_retried_until_it_succeeds(client):
    job_id = submit(client, "flaky", {"fail_times": 2})
    job = wait_for_terminal_status(client, job_id)
    assert job["status"] == "succeeded", job
    assert job["attempts"] == 3


def test_failing_job_is_dead_lettered_after_all_attempts(client):
    job_id = submit(client, "fail")
    job = wait_for_terminal_status(client, job_id)
    assert job["status"] == "failed", job
    assert job["attempts"] == MAX_ATTEMPTS
    assert job["last_error"].startswith("TaskError")

    message = wait_for_dead_letter(job_id)
    assert message["attempts"] == MAX_ATTEMPTS
    assert message["error"].startswith("TaskError")


def test_unknown_task_fails_without_retry(client):
    job_id = submit(client, "does-not-exist")
    job = wait_for_terminal_status(client, job_id)
    assert job["status"] == "failed", job
    assert job["attempts"] == 1
    assert job["last_error"].startswith("PermanentTaskError")

    message = wait_for_dead_letter(job_id)
    assert message["attempts"] == 1


def test_job_cancelled_while_waiting_for_a_retry_is_not_run_again(client):
    job_id = submit(client, "fail")
    wait_for(
        client,
        job_id,
        lambda job: job["attempts"] == 1 and job["status"] == "pending",
        "the first failed attempt",
    )
    response = client.post(f"/jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text

    time.sleep(RETRY_DELAY_MS / 1000 + 3)  # the retry message comes back, then is skipped
    job = get_job(client, job_id)
    assert job["status"] == "cancelled", job
    assert job["attempts"] == 1
