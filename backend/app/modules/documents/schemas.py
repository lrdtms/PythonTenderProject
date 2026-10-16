"""Document DTOs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class VersionDTO(BaseModel):
    id: UUID
    document_id: UUID
    version_number: int
    filename: str
    mime_type: str
    file_format: str
    file_size: int
    checksum_sha256: str
    processing_status: str
    is_current: bool
    created_at: datetime
    job_id: UUID | None = None


class DocumentDTO(BaseModel):
    id: UUID
    tender_id: UUID
    kind: str
    title: str
    created_at: datetime
    current_version: VersionDTO | None = None


class UploadResultDTO(BaseModel):
    document: DocumentDTO
    version: VersionDTO
    job_id: UUID


class ProcessingInfo(BaseModel):
    """What the ingest step needs about a version (internal)."""

    version_id: UUID
    document_id: UUID
    tender_id: UUID
    storage_key: str
    file_format: str
    filename: str
    kind: str
    tender_archived: bool = False
