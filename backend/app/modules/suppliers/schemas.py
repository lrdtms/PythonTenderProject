"""Value objects returned by the suppliers module."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class StoreResult:
    inserted: int
    duplicates_of_reviewed: int
    supplier_id: UUID
    quotation_id: UUID
    supplier_created: bool
