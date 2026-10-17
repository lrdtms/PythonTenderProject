"""Value objects returned by the suppliers module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any
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


class QuotationDTO(BaseModel):
    id: UUID
    document_version_id: UUID
    supplier_id: UUID
    supplier_name: str
    reference: str | None
    quote_date: date | None
    valid_until: date | None
    currency: str | None
    prices_include_vat: bool | None
    flags: list[str]
    item_count: int
    created_at: datetime


class QuotationPatch(BaseModel):
    """Absent means unchanged; null clears a header field. The supplier cannot be cleared."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: UUID | None = None
    reference: Annotated[str, StringConstraints(max_length=100)] | None = None
    quote_date: date | None = None
    valid_until: date | None = None
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None
    prices_include_vat: bool | None = None

    _nul = field_validator("reference")(_no_nul)

    @model_validator(mode="after")
    def _check(self) -> QuotationPatch:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        if "supplier_id" in self.model_fields_set and self.supplier_id is None:
            raise ValueError("The supplier cannot be cleared.")
        return self


class QuotationItemDTO(BaseModel):
    id: UUID
    quotation_id: UUID
    document_version_id: UUID
    run_id: UUID
    position: int
    description: str
    sku: str | None
    unit: str | None
    quantity: str | None  # decimal text; null when missing
    unit_price: str | None
    raw_unit: str | None
    raw_quantity: str | None
    raw_price: str | None
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


class QuotationItemPatch(BaseModel):
    """The fields a reviewer may change. Absent means unchanged; null clears a nullable field.
    Decimals are JSON strings, never numbers."""

    model_config = ConfigDict(extra="forbid")

    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = None
    sku: Annotated[str, StringConstraints(max_length=100)] | None = None
    unit: Annotated[str, StringConstraints(max_length=30)] | None = None
    quantity: DecimalText | None = None
    unit_price: DecimalText | None = None

    _nul = field_validator("description", "sku", "unit")(_no_nul)

    @model_validator(mode="after")
    def _check(self) -> QuotationItemPatch:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        if "description" in self.model_fields_set and self.description is None:
            raise ValueError("The description cannot be cleared.")
        return self
