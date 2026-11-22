import json
from uuid import UUID, uuid4

import pytest
from pika.exceptions import AMQPConnectionError
from sqlalchemy.orm import Session

from app.db import get_engine
from app.repository import JobRepository
from app.schemas import Job, JobCreate, JobStatus
from app.worker import (
    MAX_ATTEMPTS,
    Backoff,
    Shutdown,
    handle_message,
    process_job,
    sleep_unless_shutdown,
)
from app.worker import (
    run as run_forever,
)


class FakeDispatcher:
    def __init__(self) -> None:
        self.retried: list[UUID] = []
        self.dead: list[tuple[UUID, str, int]] = []

    def retry(self, job_id: UUID) -> None:
        self.retried.append(job_id)

    def dead_letter(self, job_id: UUID, error: str, attempts: int) -> None:
        self.dead.append((job_id, error, attempts))


class FakeChannel:
    def __init__(self) -> None:
        self.acked: list[int] = []

    def basic_ack(self, delivery_tag: int) -> None:
        self.acked.append(delivery_tag)


def make_job(task: str, payload: dict | None = None) -> UUID:
    with Session(get_engine()) as session:
        job = JobRepository(session).create(
            JobCreate(task=task, payload=payload or {})
        )
        return job.id


def run(job_id: UUID, dispatcher: FakeDispatcher) -> None:
    with Session(get_engine()) as session:
        process_job(job_id, session, dispatcher)


def get_job(job_id: UUID) -> Job:
    with Session(get_engine()) as session:
        job = JobRepository(session).get(job_id)
        assert job is not None
        return job


def cancel(job_id: UUID) -> None:
    with Session(get_engine()) as session:
        repo = JobRepository(session)
        assert repo.transition(job_id, JobStatus.PENDING, JobStatus.CANCELLED)


def test_job_succeeds_on_first_attempt():
    dispatcher = FakeDispatcher()
    job_id = make_job("report-generation", {"seconds": 0})
    run(job_id, dispatcher)
    job = get_job(job_id)
    assert job.status == JobStatus.SUCCEEDED
    assert job.attempts == 1
    assert dispatcher.retried == []
    assert dispatcher.dead == []


def test_failing_task_is_retried_then_dead_lettered():
    dispatcher = FakeDispatcher()
    job_id = make_job("fail")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        run(job_id, dispatcher)
        job = get_job(job_id)
        assert job.attempts == attempt
        if attempt < MAX_ATTEMPTS:
            assert job.status == JobStatus.PENDING
    assert job.status == JobStatus.FAILED
    assert job.last_error is not None
    assert job.last_error.startswith("TaskError")
    assert dispatcher.retried == [job_id] * (MAX_ATTEMPTS - 1)
    assert len(dispatcher.dead) == 1
    assert dispatcher.dead[0][0] == job_id
    assert dispatcher.dead[0][2] == MAX_ATTEMPTS


def test_flaky_task_succeeds_after_retries():
    dispatcher = FakeDispatcher()
    job_id = make_job("flaky", {"fail_times": 2})
    for _ in range(3):
        run(job_id, dispatcher)
    job = get_job(job_id)
    assert job.status == JobStatus.SUCCEEDED
    assert job.attempts == 3
    assert dispatcher.retried == [job_id, job_id]
    assert dispatcher.dead == []


def test_unknown_task_fails_without_retry():
    dispatcher = FakeDispatcher()
    job_id = make_job("does-not-exist")
    run(job_id, dispatcher)
    job = get_job(job_id)
    assert job.status == JobStatus.FAILED
    assert job.attempts == 1
    assert job.last_error is not None
    assert "unknown task" in job.last_error
    assert dispatcher.retried == []
    assert len(dispatcher.dead) == 1


def test_cancelled_job_is_skipped():
    dispatcher = FakeDispatcher()
    job_id = make_job("report-generation", {"seconds": 0})
    cancel(job_id)
    run(job_id, dispatcher)
    job = get_job(job_id)
    assert job.status == JobStatus.CANCELLED
    assert job.attempts == 0


def test_job_cancelled_while_waiting_for_a_retry_is_skipped():
    dispatcher = FakeDispatcher()
    job_id = make_job("fail")
    run(job_id, dispatcher)
    assert get_job(job_id).status == JobStatus.PENDING
    cancel(job_id)
    run(job_id, dispatcher)
    job = get_job(job_id)
    assert job.status == JobStatus.CANCELLED
    assert job.attempts == 1
    assert dispatcher.retried == [job_id]


def test_unknown_job_is_ignored():
    dispatcher = FakeDispatcher()
    run(uuid4(), dispatcher)
    assert dispatcher.retried == []
    assert dispatcher.dead == []


def test_malformed_message_is_acknowledged_and_dropped():
    channel = FakeChannel()
    handle_message(channel, 1, b"not json", FakeDispatcher())
    assert channel.acked == [1]


def test_valid_message_runs_the_job_then_acknowledges():
    job_id = make_job("report-generation", {"seconds": 0})
    channel = FakeChannel()
    body = json.dumps({"job_id": str(job_id)}).encode()
    handle_message(channel, 7, body, FakeDispatcher())
    assert get_job(job_id).status == JobStatus.SUCCEEDED
    assert channel.acked == [7]


def test_shutdown_flag_is_set_by_request():
    shutdown = Shutdown()
    assert not shutdown.requested
    shutdown.request(15, None)
    assert shutdown.requested


def test_backoff_doubles_up_to_the_maximum_and_resets():
    backoff = Backoff(1.0, 8.0)
    assert [backoff.next() for _ in range(5)] == [1.0, 2.0, 4.0, 8.0, 8.0]
    backoff.reset()
    assert backoff.next() == 1.0


def test_sleep_unless_shutdown_sleeps_the_requested_time_in_steps():
    slept = []
    sleep_unless_shutdown(Shutdown(), 1.5, sleep=slept.append, step=0.5)
    assert slept == [0.5, 0.5, 0.5]


def test_sleep_unless_shutdown_stops_when_a_shutdown_is_requested():
    shutdown = Shutdown()
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        shutdown.request(15, None)

    sleep_unless_shutdown(shutdown, 10.0, sleep=fake_sleep)
    assert slept == [0.5]


def test_run_reconnects_with_a_growing_delay_then_returns():
    attempts = []
    slept = []

    def serve_once(backoff):
        attempts.append(1)
        if len(attempts) < 3:
            raise AMQPConnectionError("broker down")

    run_forever(serve_once, Shutdown(), Backoff(1.0, 30.0), sleep=slept.append)
    assert len(attempts) == 3
    assert sum(slept) == 3.0  # 1 s after the first failure, 2 s after the second


def test_run_stops_reconnecting_when_a_shutdown_is_requested():
    shutdown = Shutdown()
    calls = []

    def serve_once(backoff):
        calls.append(1)
        raise AMQPConnectionError("broker down")

    def fake_sleep(seconds):
        shutdown.request(15, None)

    run_forever(serve_once, shutdown, Backoff(1.0, 30.0), sleep=fake_sleep)
    assert len(calls) == 1


def test_run_does_not_hide_unexpected_errors():
    def serve_once(backoff):
        raise ValueError("bug")

    with pytest.raises(ValueError):
        run_forever(
            serve_once, Shutdown(), Backoff(1.0, 30.0), sleep=lambda seconds: None
        )
