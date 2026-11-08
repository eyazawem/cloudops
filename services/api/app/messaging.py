import json
import os
from typing import Any
from uuid import UUID

import pika
from pika.adapters.blocking_connection import BlockingChannel

QUEUE_NAME = "jobs"
RETRY_QUEUE_NAME = "jobs.retry"
DEAD_LETTER_QUEUE_NAME = "jobs.dead"
# Messages wait this long in the retry queue, then RabbitMQ dead-letters them
# back to the main queue. Changing it requires deleting the queue first.
RETRY_DELAY_MS = 5000


def get_rabbitmq_url() -> str:
    url = os.environ.get("RABBITMQ_URL")
    if not url:
        raise RuntimeError("RABBITMQ_URL environment variable is not set")
    return url


def connect() -> pika.BlockingConnection:
    return pika.BlockingConnection(pika.URLParameters(get_rabbitmq_url()))


def declare_queues(channel: BlockingChannel) -> None:
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.queue_declare(
        queue=RETRY_QUEUE_NAME,
        durable=True,
        arguments={
            "x-message-ttl": RETRY_DELAY_MS,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": QUEUE_NAME,
        },
    )
    channel.queue_declare(queue=DEAD_LETTER_QUEUE_NAME, durable=True)


def _publish(routing_key: str, message: dict[str, Any]) -> None:
    """Publish a persistent message. Raises if the broker does not confirm it."""
    connection = connect()
    try:
        channel = connection.channel()
        declare_queues(channel)
        channel.confirm_delivery()
        channel.basic_publish(
            exchange="",
            routing_key=routing_key,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
            ),
            mandatory=True,
        )
    finally:
        if connection.is_open:
            connection.close()


def publish_job(job_id: UUID) -> None:
    _publish(QUEUE_NAME, {"job_id": str(job_id)})


def publish_retry(job_id: UUID) -> None:
    _publish(RETRY_QUEUE_NAME, {"job_id": str(job_id)})


def publish_dead_letter(job_id: UUID, error: str, attempts: int) -> None:
    _publish(
        DEAD_LETTER_QUEUE_NAME,
        {"job_id": str(job_id), "error": error, "attempts": attempts},
    )
