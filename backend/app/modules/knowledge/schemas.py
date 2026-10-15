"""Knowledge DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class PageDTO(BaseModel):
    page_number: int
    label: str | None
    status: str
    text_source: str
    ocr_confidence: float | None
    char_count: int
    table_count: int


class PageDetailDTO(PageDTO):
    text: str
    tables: list[Any]


class SearchHitDTO(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    version_id: UUID
    version_number: int
    page_number: int
    section: str | None
    snippet: str
    rank: float


@dataclass
class IngestResult:
    pages: int
    chunks: int
    warnings: list[dict[str, Any]] = field(default_factory=list)
