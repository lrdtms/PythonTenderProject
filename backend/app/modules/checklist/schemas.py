from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

from app.kernel.vocab import MANDATORY_STATUSES, REQUIREMENT_TYPES

RequirementType = Literal[*REQUIREMENT_TYPES]
MandatoryStatus = Literal[*MANDATORY_STATUSES]


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
    original_value: dict[str, Any] = {}
    reviewed_by: UUID | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None


class RequirementPatch(BaseModel):
    """The fields a reviewer may change. The evidence quote and its location are not editable."""

    model_config = ConfigDict(extra="forbid")

    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = None
    requirement_type: RequirementType | None = None
    mandatory_status: MandatoryStatus | None = None

    @field_validator("description")
    @classmethod
    def _no_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("Text cannot contain NUL characters.")
        return value

    @model_validator(mode="after")
    def _check(self) -> RequirementPatch:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be cleared.")
        return self
