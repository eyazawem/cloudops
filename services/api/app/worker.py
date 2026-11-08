import json
import logging
from uuid import UUID

from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from sqlalchemy.orm import Session

from app import messaging
from app.db import get_engine
from app.repository import JobRepository
from app.schemas import JobStatus
from app.tasks import HANDLERS, TaskError

logger = logging.getLogger("worker")


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


def on_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
) -> None:
    try:
        job_id = UUID(json.loads(body)["job_id"])
    except (ValueError, KeyError, TypeError):
        logger.error("malformed message, dropping: %r", body)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    with Session(get_engine()) as session:
        process_job(job_id, session)
    channel.basic_ack(delivery_tag=method.delivery_tag)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("pika").setLevel(logging.WARNING)
    connection = messaging.connect()
    channel = connection.channel()
    messaging.declare_queue(channel)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(
        queue=messaging.QUEUE_NAME, on_message_callback=on_message
    )
    logger.info("worker started, waiting for jobs")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
