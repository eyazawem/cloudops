from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import JobRecord
from app.schemas import Job, JobCreate, JobStatus


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, data: JobCreate) -> Job:
        record = JobRecord(
            task=data.task,
            payload=data.payload,
            status=JobStatus.PENDING.value,
        )
        self._session.add(record)
        self._session.commit()
        self._session.refresh(record)
        return Job.model_validate(record)

    def get(self, job_id: UUID) -> Job | None:
        record = self._session.get(JobRecord, job_id)
        return Job.model_validate(record) if record else None

    def list_all(self) -> list[Job]:
        stmt = select(JobRecord).order_by(JobRecord.created_at)
        return [Job.model_validate(r) for r in self._session.scalars(stmt)]

    def transition(
        self,
        job_id: UUID,
        expected: JobStatus,
        new: JobStatus,
        last_error: str | None = None,
    ) -> bool:
        """Atomically move a job from `expected` to `new`.

        Returns False, without changing anything, if the job is not in the
        `expected` status (or does not exist).
        """
        values: dict[str, Any] = {"status": new.value}
        if last_error is not None:
            values["last_error"] = last_error
        stmt = (
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .where(JobRecord.status == expected.value)
            .values(**values)
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount == 1

    def claim(self, job_id: UUID) -> int | None:
        """Atomically move a pending job to running and count the attempt.

        Returns the attempt number, or None if the job is not pending.
        """
        stmt = (
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .where(JobRecord.status == JobStatus.PENDING.value)
            .values(status=JobStatus.RUNNING.value, attempts=JobRecord.attempts + 1)
            .returning(JobRecord.attempts)
        )
        attempt = self._session.execute(stmt).scalar_one_or_none()
        self._session.commit()
        return attempt
