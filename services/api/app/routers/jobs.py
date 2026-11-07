from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.schemas import Job, JobCreate, JobStatus
from app.store import job_store

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_job(data: JobCreate) -> Job:
    return job_store.create(data)


@router.get("", response_model=list[Job])
def list_jobs() -> list[Job]:
    return job_store.list_all()


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: UUID) -> Job:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: UUID) -> Job:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Only pending jobs can be cancelled (current: {job.status})",
        )
    return job_store.set_status(job_id, JobStatus.CANCELLED)
