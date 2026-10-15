from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.modules.jobs import public as jobs


class RunDTO(BaseModel):
    id: UUID
    document_version_id: UUID
    job_id: UUID
    kind: str
    status: str
    deep_scan: bool
    prompt_version: str | None
    filter_version: str | None
    schema_version: str | None
    model: str | None
    warnings: list[Any]
    counts: dict[str, Any]
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class KindStatusDTO(BaseModel):
    kind: str
    job: jobs.JobDTO | None
    run: RunDTO | None


class ExtractionStatusDTO(BaseModel):
    kinds: list[KindStatusDTO]
