"""Plain data types of the extraction core. No I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class PageInput:
    """One ingested page or sheet, as stored by `knowledge`."""

    page_number: int
    label: str | None
    text: str
    text_source: str
    status: str
    tables: list[Any] = field(default_factory=list)


SOURCE_STRIDE = 1_000_000
SOURCE_UNLOCATED = 2_000_000_000  # below int32 max; sorts after every located item


def source_order(page_number: int | None, position: int | None) -> int:
    """Document-order sort key: page (or sheet) first, then the position inside it. Items whose
    page is unknown (unverified evidence) sort last."""
    if page_number is None:
        return SOURCE_UNLOCATED
    inside = max(0, min(position or 0, SOURCE_STRIDE - 1))
    return min(page_number, 1999) * SOURCE_STRIDE + inside


# Column widths of boq_items (migration 0003). The parser clips to these and flags `truncated`,
# so one oversized cell can never fail the insert of a whole BoQ.
BOQ_TEXT_LIMITS: dict[str, int] = {
    "section": 300, "item_no": 50, "unit": 30, "raw_unit": 50, "raw_quantity": 50,
    "sheet": 200, "cell_range": 40,
}  # fmt: skip


@dataclass
class BoqCandidate:
    section: str | None
    item_no: str | None
    description: str
    unit: str | None
    quantity: Decimal | None
    rate: Decimal | None
    raw_unit: str | None
    raw_quantity: str | None
    flags: list[str]
    page_number: int | None
    sheet: str | None
    cell_range: str | None
    source_order: int = 0

    def as_row(self) -> dict[str, Any]:
        return {
            "section": self.section, "item_no": self.item_no, "description": self.description,
            "unit": self.unit, "quantity": self.quantity, "rate": self.rate,
            "raw_unit": self.raw_unit, "raw_quantity": self.raw_quantity, "flags": list(self.flags),
            "page_number": self.page_number, "sheet": self.sheet, "cell_range": self.cell_range,
            "source_order": self.source_order,
        }  # fmt: skip


@dataclass
class BoqResult:
    items: list[BoqCandidate] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    boq_pages: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class Window:
    text: str
    pages: tuple[int, ...]


@dataclass
class RequirementCandidate:
    description: str
    requirement_type: str
    mandatory_status: str
    evidence_quote: str
    page_number: int | None = None
    quote_start: int | None = None
    quote_end: int | None = None
    evidence_status: str = "verified"
    needs_review: bool = False

    def as_row(self) -> dict[str, Any]:
        return {
            "description": self.description, "requirement_type": self.requirement_type,
            "mandatory_status": self.mandatory_status, "evidence_quote": self.evidence_quote,
            "page_number": self.page_number, "quote_start": self.quote_start,
            "quote_end": self.quote_end, "evidence_status": self.evidence_status,
            "needs_review": self.needs_review,
            "source_order": source_order(self.page_number, self.quote_start),
        }  # fmt: skip
