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

    def cancel_if_pending(self, job_id: UUID) -> bool:
        """Atomically cancel a job only if it is still pending."""
        stmt = (
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .where(JobRecord.status == JobStatus.PENDING.value)
            .values(status=JobStatus.CANCELLED.value)
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount == 1
