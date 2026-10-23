"""Export value objects: plain renderer inputs (no database, no framework types) and the API
shapes (`ExportCreate`, `ExportDTO`)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

ExportKind = Literal["estimate_xlsx", "checklist_pdf"]
ExportLabel = Literal["draft", "reviewed", "approved"]


@dataclass(frozen=True)
class ExportTotals:
    subtotal_cost: Decimal
    markup_total: Decimal
    subtotal_ex_vat: Decimal
    vat_total: Decimal
    total_inc_vat: Decimal


@dataclass(frozen=True)
class ExportLine:
    """One estimate line, exactly as the estimate DTO reports it (the mapper, which is not part
    of this module, only converts text to Decimal).

    For a "changed" line the input carries the quote values the line was *priced with* (the stored,
    old values: supplier, quoted price, currency, VAT basis), never the live quote. Amounts are
    reported by the renderer as empty for every status except "priced", so a changed line never
    shows a figure; the status "Source changed" and its note tell the reader to re-price it.
    """

    position: int
    section: str | None
    item_no: str | None
    description: str
    unit: str | None
    quantity: Decimal | None
    price_source: Literal["supplier", "manual", "excluded", "unresolved"]
    supplier_name: str | None
    quoted_unit_price: Decimal | None
    quoted_currency: str | None
    quoted_includes_vat: bool | None
    unit_price_ex_vat: Decimal | None
    labour_rate: Decimal | None
    material_cost: Decimal | None
    labour_cost: Decimal | None
    cost: Decimal | None
    markup_percent: Decimal | None
    markup: Decimal | None
    total: Decimal | None
    status: Literal["priced", "excluded", "unresolved", "changed"]
    flags: tuple[str, ...]
    exclude_reason: str | None


@dataclass(frozen=True)
class EstimateExportInput:
    tender_title: str
    tender_reference: str
    client_name: str | None
    version: int
    status: Literal["draft", "reviewed", "approved"]
    currency: str
    vat_rate: Decimal
    markup_basis: Literal["cost", "selling_price"]
    markup_percent: Decimal
    totals: ExportTotals | None
    priced: int
    excluded: int
    unresolved: int
    changed: int
    incomplete: bool
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    approved_by_name: str | None
    approved_at: datetime | None
    generated_by_name: str | None
    lines: tuple[ExportLine, ...]
    generated_at: datetime | None = None
    export_id: UUID | None = None


@dataclass(frozen=True)
class ChecklistRow:
    requirement_type: str
    mandatory_status: str
    description: str
    review_status: str
    document_title: str
    page_number: int | None
    evidence_verified: bool


@dataclass(frozen=True)
class ChecklistExportInput:
    tender_title: str
    tender_reference: str | None
    client_name: str | None
    closing_at: datetime | None
    generated_by_name: str | None
    rows: tuple[ChecklistRow, ...]
    rejected_count: int
    generated_at: datetime | None = None
    export_id: UUID | None = None


class ExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ExportKind
    estimate_id: UUID | None = None

    @model_validator(mode="after")
    def _estimate_only_for_estimates(self) -> "ExportCreate":
        if self.estimate_id is not None and self.kind != "estimate_xlsx":
            raise ValueError("estimate_id is only allowed for an estimate export")
        return self


class ExportDTO(BaseModel):
    id: UUID
    tender_id: UUID
    kind: ExportKind
    estimate_id: UUID | None
    estimate_version: int | None
    label: ExportLabel
    file_name: str
    content_type: str
    file_size: int
    row_count: int
    generated_by: UUID
    generated_by_name: str | None = None
    generated_at: datetime
