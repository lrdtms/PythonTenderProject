from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator


@dataclass(frozen=True)
class ReplaceResult:
    inserted: int
    duplicates_of_reviewed: int


class BoqItemDTO(BaseModel):
    id: UUID
    run_id: UUID
    document_version_id: UUID
    position: int
    section: str | None
    item_no: str | None
    description: str
    unit: str | None
    quantity: str | None  # decimal text, e.g. "10.5000"; null when missing
    rate: str | None
    raw_unit: str | None
    raw_quantity: str | None
    flags: list[str]
    page_number: int | None
    sheet: str | None
    cell_range: str | None
    review_status: str
    corrected_value: dict[str, Any] | None
    original_value: dict[str, Any] = {}
    reviewed_by: UUID | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None


DecimalText = Annotated[str, StringConstraints(pattern=r"^-?\d{1,14}(\.\d{1,4})?$")]


class BoqPatch(BaseModel):
    """The fields a reviewer may change. Absent means unchanged; null clears a nullable field.
    Decimals are JSON strings, never numbers."""

    model_config = ConfigDict(extra="forbid")

    section: Annotated[str, StringConstraints(max_length=300)] | None = None
    item_no: Annotated[str, StringConstraints(max_length=50)] | None = None
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = None
    unit: Annotated[str, StringConstraints(max_length=30)] | None = None
    quantity: DecimalText | None = None
    rate: DecimalText | None = None

    @field_validator("description", "section", "item_no", "unit")
    @classmethod
    def _no_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("Text cannot contain NUL characters.")
        return value

    @model_validator(mode="after")
    def _check(self) -> BoqPatch:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        if "description" in self.model_fields_set and self.description is None:
            raise ValueError("The description cannot be cleared.")
        return self
