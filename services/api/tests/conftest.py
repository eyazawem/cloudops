import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from pika.exceptions import AMQPConnectionError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_engine
from app.main import app
from app.routers.jobs import get_publisher

_test_url = os.environ.get("TEST_DATABASE_URL")
if not _test_url:
    pytest.exit(
        "TEST_DATABASE_URL is not set (run: source scripts/dev-env.sh)",
        returncode=2,
    )
if not _test_url.rsplit("/", 1)[-1].endswith("_test"):
    pytest.exit(
        "TEST_DATABASE_URL must point to a database whose name ends with _test",
        returncode=2,
    )

# The application and Alembic read DATABASE_URL: point them at the test database.
os.environ["DATABASE_URL"] = _test_url

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


class FakePublisher:
    """Stands in for RabbitMQ in API tests."""

    def __init__(self) -> None:
        self.published: list[UUID] = []
        self.fail = False

    def __call__(self, job_id: UUID) -> None:
        if self.fail:
            raise AMQPConnectionError("queue is down")
        self.published.append(job_id)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    command.upgrade(Config(str(ALEMBIC_INI)), "head")


@pytest.fixture(autouse=True)
def clean_jobs(migrated_database: None) -> None:
    with Session(get_engine()) as session:
        session.execute(text("TRUNCATE TABLE jobs"))
        session.commit()


@pytest.fixture(autouse=True)
def publisher() -> Iterator[FakePublisher]:
    fake = FakePublisher()
    app.dependency_overrides[get_publisher] = lambda: fake
    yield fake
    app.dependency_overrides.clear()
