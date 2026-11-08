from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobCreate(BaseModel):
    task: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task: str
    payload: dict[str, Any]
    status: JobStatus
    attempts: int
    last_error: str | None
    created_at: datetime
