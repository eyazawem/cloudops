import json
import logging
import signal
import time
from collections.abc import Callable
from types import FrameType
from typing import Protocol
from uuid import UUID

from pika.exceptions import AMQPError
from sqlalchemy.orm import Session

from app import messaging
from app.db import get_engine
from app.repository import JobRepository
from app.schemas import JobStatus
from app.tasks import HANDLERS, PermanentTaskError

logger = logging.getLogger("worker")

MAX_ATTEMPTS = 3
RECONNECT_MIN_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 30.0


class SupportsAck(Protocol):
    def basic_ack(self, delivery_tag: int) -> None: ...


class Dispatcher(Protocol):
    def retry(self, job_id: UUID) -> None: ...

    def dead_letter(self, job_id: UUID, error: str, attempts: int) -> None: ...


class RabbitDispatcher:
    """Sends retry and dead-letter messages through RabbitMQ."""

    def retry(self, job_id: UUID) -> None:
        messaging.publish_retry(job_id)

    def dead_letter(self, job_id: UUID, error: str, attempts: int) -> None:
        messaging.publish_dead_letter(job_id, error, attempts)


class Shutdown:
    """Set by SIGTERM/SIGINT. The main loop checks it between jobs."""

    def __init__(self) -> None:
        self.requested = False

    def request(self, signum: int, frame: FrameType | None) -> None:
        self.requested = True


class Backoff:
    """Delay that doubles after each failure, up to a maximum."""

    def __init__(self, minimum: float, maximum: float) -> None:
        self.minimum = minimum
        self.maximum = maximum
        self.delay = minimum

    def next(self) -> float:
        current = self.delay
        self.delay = min(self.delay * 2, self.maximum)
        return current

    def reset(self) -> None:
        self.delay = self.minimum


def process_job(
    job_id: UUID,
    session: Session,
    dispatcher: Dispatcher,
    max_attempts: int = MAX_ATTEMPTS,
) -> None:
    """Run one attempt of a job.

    A job that is not pending (e.g. cancelled) is skipped. A failed attempt is
    retried until `max_attempts`; after that, or on a permanent failure, the job
    is marked failed and reported to the dead-letter queue.
    """
    repo = JobRepository(session)
    job = repo.get(job_id)
    if job is None:
        logger.warning("job %s not found, dropping message", job_id)
        return
    attempt = repo.claim(job_id)
    if attempt is None:
        logger.info("job %s is not pending (%s), skipping", job_id, job.status)
        return

    logger.info(
        "job %s running (task=%s, attempt %d/%d)",
        job_id,
        job.task,
        attempt,
        max_attempts,
    )
    try:
        handler = HANDLERS.get(job.task)
        if handler is None:
            raise PermanentTaskError(f"unknown task: {job.task}")
        handler(job.payload, attempt)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if not isinstance(exc, PermanentTaskError) and attempt < max_attempts:
            logger.warning(
                "job %s failed (attempt %d/%d), retry in %d s: %s",
                job_id,
                attempt,
                max_attempts,
                messaging.RETRY_DELAY_MS // 1000,
                error,
            )
            if repo.transition(
                job_id, JobStatus.RUNNING, JobStatus.PENDING, last_error=error
            ):
                dispatcher.retry(job_id)
            return
        logger.exception(
            "job %s failed for good (attempt %d/%d): %s",
            job_id,
            attempt,
            max_attempts,
            error,
        )
        repo.transition(job_id, JobStatus.RUNNING, JobStatus.FAILED, last_error=error)
        dispatcher.dead_letter(job_id, error, attempt)
        return

    repo.transition(job_id, JobStatus.RUNNING, JobStatus.SUCCEEDED)
    logger.info("job %s succeeded", job_id)


def handle_message(
    channel: SupportsAck,
    delivery_tag: int,
    body: bytes,
    dispatcher: Dispatcher,
) -> None:
    """Process one message, then acknowledge it."""
    try:
        job_id = UUID(json.loads(body)["job_id"])
    except (ValueError, KeyError, TypeError):
        logger.error("malformed message, dropping: %r", body)
        channel.basic_ack(delivery_tag=delivery_tag)
        return

    with Session(get_engine()) as session:
        process_job(job_id, session, dispatcher)
    channel.basic_ack(delivery_tag=delivery_tag)


def sleep_unless_shutdown(
    shutdown: Shutdown,
    seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    step: float = 0.5,
) -> None:
    """Sleep for `seconds`, in short steps so that a shutdown request is noticed."""
    remaining = seconds
    while remaining > 0 and not shutdown.requested:
        pause = min(step, remaining)
        sleep(pause)
        remaining -= pause


def serve(shutdown: Shutdown, dispatcher: Dispatcher, backoff: Backoff) -> None:
    """Consume jobs until a shutdown is requested. Raises if the connection is lost."""
    connection = messaging.connect()
    try:
        channel = connection.channel()
        messaging.declare_queues(channel)
        channel.basic_qos(prefetch_count=1)
        backoff.reset()
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
            handle_message(channel, method.delivery_tag, body, dispatcher)
            if shutdown.requested:
                break

        requeued = channel.cancel()
        logger.info(
            "worker stopped (%d pending message(s) returned to the queue)", requeued
        )
    finally:
        if connection.is_open:
            connection.close()


def run(
    serve_once: Callable[[Backoff], None],
    shutdown: Shutdown,
    backoff: Backoff,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Call `serve_once` until it returns.

    When the connection to RabbitMQ is lost or unavailable, wait with a growing
    delay and try again. Any other error is not caught: it stops the worker.
    """
    while not shutdown.requested:
        try:
            serve_once(backoff)
            return
        except (AMQPError, OSError) as exc:
            delay = backoff.next()
            logger.warning(
                "RabbitMQ connection lost or unavailable (%s: %s), retrying in %.0f s",
                type(exc).__name__,
                exc,
                delay,
            )
            sleep_unless_shutdown(shutdown, delay, sleep)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("pika").setLevel(logging.WARNING)

    shutdown = Shutdown()
    signal.signal(signal.SIGTERM, shutdown.request)
    signal.signal(signal.SIGINT, shutdown.request)
    dispatcher = RabbitDispatcher()
    backoff = Backoff(RECONNECT_MIN_SECONDS, RECONNECT_MAX_SECONDS)
    run(lambda b: serve(shutdown, dispatcher, b), shutdown, backoff)


if __name__ == "__main__":
    main()
