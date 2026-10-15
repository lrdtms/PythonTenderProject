from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel


@dataclass(frozen=True)
class ReplaceResult:
    inserted: int
    duplicates_of_reviewed: int


class RequirementDTO(BaseModel):
    id: UUID
    run_id: UUID
    document_version_id: UUID
    position: int
    description: str
    requirement_type: str
    mandatory_status: str
    evidence_quote: str
    evidence_status: str
    needs_review: bool
    page_number: int | None
    quote_start: int | None
    quote_end: int | None
    review_status: str
    corrected_value: dict[str, Any] | None
