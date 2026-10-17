"""Value objects returned by the suppliers module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator


@dataclass(frozen=True)
class StoreResult:
    inserted: int
    duplicates_of_reviewed: int
    supplier_id: UUID
    quotation_id: UUID
    supplier_created: bool


@dataclass(frozen=True)
class MatchResult:
    suggested: int
    kept_decided: int
    removed_suggested: int


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Notes = Annotated[str, StringConstraints(max_length=2000)]


def _no_nul(value: str | None) -> str | None:
    if value is not None and "\x00" in value:
        raise ValueError("Text cannot contain NUL characters.")
    return value


class SupplierDTO(BaseModel):
    id: UUID
    name: str
    notes: str | None
    quotation_count: int
    created_at: datetime


class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    notes: Notes | None = None

    _nul = field_validator("name", "notes")(_no_nul)


class SupplierPatch(BaseModel):
    """Absent means unchanged; null clears the notes. The name cannot be cleared."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    notes: Notes | None = None

    _nul = field_validator("name", "notes")(_no_nul)

    @model_validator(mode="after")
    def _check(self) -> SupplierPatch:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("The name cannot be cleared.")
        return self


class SupplierMerge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    into_id: UUID
