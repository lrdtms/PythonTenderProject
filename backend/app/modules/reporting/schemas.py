"""Plain input dataclasses for the export renderers (no database, no framework types)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class ExportTotals:
    subtotal_cost: Decimal
    markup_total: Decimal
    subtotal_ex_vat: Decimal
    vat_total: Decimal
    total_inc_vat: Decimal


@dataclass(frozen=True)
class ExportLine:
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
    generated_by_name: str
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
    generated_by_name: str
    rows: tuple[ChecklistRow, ...]
    rejected_count: int
    generated_at: datetime | None = None
    export_id: UUID | None = None
