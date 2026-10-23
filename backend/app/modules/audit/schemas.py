"""Audit read DTOs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AuditFilters(BaseModel):
    entity_type: str | None = None
    action: str | None = None
    user_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


class AuditEventDTO(BaseModel):
    id: UUID
    created_at: datetime
    user_id: UUID | None
    entity_type: str
    entity_id: UUID | None
    action: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditPage(BaseModel):
    items: list[AuditEventDTO]
    next_cursor: str | None


class AuditFacets(BaseModel):
    entity_types: list[str]
    actions: list[str]
