from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.repository import JobRepository
from app.schemas import Job, JobCreate, JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_repository(
    session: Annotated[Session, Depends(get_session)],
) -> JobRepository:
    return JobRepository(session)


Repository = Annotated[JobRepository, Depends(get_repository)]


@router.post("", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_job(data: JobCreate, repo: Repository) -> Job:
    return repo.create(data)


@router.get("", response_model=list[Job])
def list_jobs(repo: Repository) -> list[Job]:
    return repo.list_all()


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: UUID, repo: Repository) -> Job:
    job = repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: UUID, repo: Repository) -> Job:
    job = repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not repo.cancel_if_pending(job_id):
        raise HTTPException(
            status_code=409, detail="Only pending jobs can be cancelled"
        )
    return job.model_copy(update={"status": JobStatus.CANCELLED})
