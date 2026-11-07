from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.schemas import Job, JobCreate, JobStatus


class JobStore:
    """In-memory job storage. To be replaced by PostgreSQL."""

    def __init__(self) -> None:
        self._jobs: dict[UUID, Job] = {}

    def create(self, data: JobCreate) -> Job:
        job = Job(
            id=uuid4(),
            task=data.task,
            payload=data.payload,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        self._jobs[job.id] = job
        return job

    def get(self, job_id: UUID) -> Job | None:
        return self._jobs.get(job_id)

    def list_all(self) -> list[Job]:
        return list(self._jobs.values())

    def set_status(self, job_id: UUID, new_status: JobStatus) -> Job:
        job = self._jobs[job_id].model_copy(update={"status": new_status})
        self._jobs[job_id] = job
        return job

    def clear(self) -> None:
        self._jobs.clear()


job_store = JobStore()
