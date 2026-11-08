import json
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.db import get_engine
from app.repository import JobRepository
from app.schemas import JobCreate, JobStatus
from app.worker import Shutdown, handle_message, process_job


def make_job(task: str, payload: dict | None = None) -> UUID:
    with Session(get_engine()) as session:
        job = JobRepository(session).create(
            JobCreate(task=task, payload=payload or {})
        )
        return job.id


def run(job_id: UUID) -> None:
    with Session(get_engine()) as session:
        process_job(job_id, session)


def status_of(job_id: UUID) -> JobStatus:
    with Session(get_engine()) as session:
        job = JobRepository(session).get(job_id)
        assert job is not None
        return job.status


def test_job_succeeds():
    job_id = make_job("report-generation", {"seconds": 0})
    run(job_id)
    assert status_of(job_id) == JobStatus.SUCCEEDED


def test_failing_task_marks_job_failed():
    job_id = make_job("fail")
    run(job_id)
    assert status_of(job_id) == JobStatus.FAILED


def test_unknown_task_marks_job_failed():
    job_id = make_job("does-not-exist")
    run(job_id)
    assert status_of(job_id) == JobStatus.FAILED


def test_cancelled_job_is_skipped():
    job_id = make_job("report-generation", {"seconds": 0})
    with Session(get_engine()) as session:
        repo = JobRepository(session)
        assert repo.transition(job_id, JobStatus.PENDING, JobStatus.CANCELLED)
    run(job_id)
    assert status_of(job_id) == JobStatus.CANCELLED


def test_unknown_job_is_ignored():
    run(uuid4())


class FakeChannel:
    def __init__(self) -> None:
        self.acked: list[int] = []

    def basic_ack(self, delivery_tag: int) -> None:
        self.acked.append(delivery_tag)


def test_malformed_message_is_acknowledged_and_dropped():
    channel = FakeChannel()
    handle_message(channel, 1, b"not json")
    assert channel.acked == [1]


def test_valid_message_runs_the_job_then_acknowledges():
    job_id = make_job("report-generation", {"seconds": 0})
    channel = FakeChannel()
    handle_message(channel, 7, json.dumps({"job_id": str(job_id)}).encode())
    assert status_of(job_id) == JobStatus.SUCCEEDED
    assert channel.acked == [7]


def test_shutdown_flag_is_set_by_request():
    shutdown = Shutdown()
    assert not shutdown.requested
    shutdown.request(15, None)
    assert shutdown.requested
