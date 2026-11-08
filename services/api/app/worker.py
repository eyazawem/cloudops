import json
import logging
import signal
from types import FrameType
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app import messaging
from app.db import get_engine
from app.repository import JobRepository
from app.schemas import JobStatus
from app.tasks import HANDLERS, TaskError

logger = logging.getLogger("worker")


class SupportsAck(Protocol):
    def basic_ack(self, delivery_tag: int) -> None: ...


class Shutdown:
    """Set by SIGTERM/SIGINT. The main loop checks it between jobs."""

    def __init__(self) -> None:
        self.requested = False

    def request(self, signum: int, frame: FrameType | None) -> None:
        self.requested = True


def process_job(job_id: UUID, session: Session) -> None:
    """Run one job. A job that is not pending (e.g. cancelled) is skipped."""
    repo = JobRepository(session)
    job = repo.get(job_id)
    if job is None:
        logger.warning("job %s not found, dropping message", job_id)
        return
    if not repo.transition(job_id, JobStatus.PENDING, JobStatus.RUNNING):
        logger.info("job %s is not pending (%s), skipping", job_id, job.status)
        return

    logger.info("job %s running (task=%s)", job_id, job.task)
    try:
        handler = HANDLERS.get(job.task)
        if handler is None:
            raise TaskError(f"unknown task: {job.task}")
        handler(job.payload)
    except Exception:
        logger.exception("job %s failed", job_id)
        repo.transition(job_id, JobStatus.RUNNING, JobStatus.FAILED)
        return

    repo.transition(job_id, JobStatus.RUNNING, JobStatus.SUCCEEDED)
    logger.info("job %s succeeded", job_id)


def handle_message(channel: SupportsAck, delivery_tag: int, body: bytes) -> None:
    """Process one message, then acknowledge it."""
    try:
        job_id = UUID(json.loads(body)["job_id"])
    except (ValueError, KeyError, TypeError):
        logger.error("malformed message, dropping: %r", body)
        channel.basic_ack(delivery_tag=delivery_tag)
        return

    with Session(get_engine()) as session:
        process_job(job_id, session)
    channel.basic_ack(delivery_tag=delivery_tag)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("pika").setLevel(logging.WARNING)

    shutdown = Shutdown()
    signal.signal(signal.SIGTERM, shutdown.request)
    signal.signal(signal.SIGINT, shutdown.request)

    connection = messaging.connect()
    try:
        channel = connection.channel()
        messaging.declare_queue(channel)
        channel.basic_qos(prefetch_count=1)
        logger.info("worker started, waiting for jobs")

        for method, _properties, body in channel.consume(
            messaging.QUEUE_NAME, inactivity_timeout=1.0
        ):
            if method is None:  # no message for 1 s: only check the flag
                if shutdown.requested:
                    break
                continue
            if shutdown.requested:
                channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                break
            handle_message(channel, method.delivery_tag, body)
            if shutdown.requested:
                break

        requeued = channel.cancel()
        logger.info(
            "worker stopped (%d pending message(s) returned to the queue)", requeued
        )
    finally:
        if connection.is_open:
            connection.close()


if __name__ == "__main__":
    main()
