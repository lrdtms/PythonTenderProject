"""Request and response models for tenders."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TenderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    reference_number: str | None = Field(default=None, max_length=100)
    client_name: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    closing_at: datetime | None = None


class TenderUpdate(BaseModel):
    """Only fields that are present are changed."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    reference_number: str | None = Field(default=None, max_length=100)
    client_name: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    closing_at: datetime | None = None
    status: str | None = None


class TenderDTO(BaseModel):
    id: UUID
    title: str
    reference_number: str | None
    client_name: str | None
    location: str | None
    closing_at: datetime | None
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
