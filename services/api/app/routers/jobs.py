import logging
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pika.exceptions import AMQPError
from sqlalchemy.orm import Session

from app import messaging
from app.db import get_session
from app.repository import JobRepository
from app.schemas import Job, JobCreate, JobStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

Publisher = Callable[[UUID], None]


def get_repository(
    session: Annotated[Session, Depends(get_session)],
) -> JobRepository:
    return JobRepository(session)


def get_publisher() -> Publisher:
    return messaging.publish_job


Repository = Annotated[JobRepository, Depends(get_repository)]
PublisherDep = Annotated[Publisher, Depends(get_publisher)]


@router.post("", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_job(data: JobCreate, repo: Repository, publish: PublisherDep) -> Job:
    job = repo.create(data)
    try:
        publish(job.id)
    except (AMQPError, OSError) as exc:
        logger.error("could not enqueue job %s: %s", job.id, exc)
        repo.transition(job.id, JobStatus.PENDING, JobStatus.FAILED)
        raise HTTPException(
            status_code=503, detail="Job queue unavailable"
        ) from exc
    return job


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
    if not repo.transition(job_id, JobStatus.PENDING, JobStatus.CANCELLED):
        raise HTTPException(
            status_code=409, detail="Only pending jobs can be cancelled"
        )
    return job.model_copy(update={"status": JobStatus.CANCELLED})
