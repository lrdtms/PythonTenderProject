from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


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
