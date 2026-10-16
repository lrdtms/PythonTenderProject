"""Knowledge DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# Search highlight markers. Snippets are plain document text, never HTML.
HIGHLIGHT_START = "⟦"  # MATHEMATICAL LEFT WHITE SQUARE BRACKET
HIGHLIGHT_END = "⟧"  # MATHEMATICAL RIGHT WHITE SQUARE BRACKET


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


class ExtractionPageDTO(BaseModel):
    """Everything extraction reads about one page or sheet (internal, worker only)."""

    page_number: int
    label: str | None
    text: str
    text_source: str
    status: str
    tables: list[Any]


class SearchHitDTO(BaseModel):
    """`snippet` is raw document text (untrusted, may contain `<`, `&` or markup) with each match
    wrapped in HIGHLIGHT_START/HIGHLIGHT_END. Clients must escape it and never render it as HTML."""

    chunk_id: UUID
    document_id: UUID
    document_title: str
    version_id: UUID
    version_number: int
    page_number: int
    section: str | None
    snippet: str = Field(
        description="Plain text, never HTML: escape it before display. Matches are wrapped in "
        f"{HIGHLIGHT_START} and {HIGHLIGHT_END}."
    )
    rank: float


@dataclass
class IngestResult:
    pages: int
    chunks: int
    warnings: list[dict[str, Any]] = field(default_factory=list)
