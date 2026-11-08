import json
import os
from uuid import UUID

import pika
from pika.adapters.blocking_connection import BlockingChannel

QUEUE_NAME = "jobs"


def get_rabbitmq_url() -> str:
    url = os.environ.get("RABBITMQ_URL")
    if not url:
        raise RuntimeError("RABBITMQ_URL environment variable is not set")
    return url


def connect() -> pika.BlockingConnection:
    return pika.BlockingConnection(pika.URLParameters(get_rabbitmq_url()))


def declare_queue(channel: BlockingChannel) -> None:
    channel.queue_declare(queue=QUEUE_NAME, durable=True)


def publish_job(job_id: UUID) -> None:
    """Publish a job message. Raises if the broker does not confirm it."""
    connection = connect()
    try:
        channel = connection.channel()
        declare_queue(channel)
        channel.confirm_delivery()
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps({"job_id": str(job_id)}),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
            ),
            mandatory=True,
        )
    finally:
        if connection.is_open:
            connection.close()
