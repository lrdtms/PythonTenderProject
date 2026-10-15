"""Job DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class JobDTO(BaseModel):
    id: UUID
    job_type: str
    subject_type: str
    subject_id: UUID
    status: str
    attempt_count: int
    progress_done: int
    progress_total: int
    error_code: str | None
    warnings: list[Any]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class ClaimedJob:
    """What the worker needs. Organisation and user come from the job row, never from content."""

    id: UUID
    organisation_id: UUID
    job_type: str
    subject_type: str
    subject_id: UUID
    payload: dict[str, Any]
    attempt_count: int
    max_attempts: int
    created_by: UUID | None
