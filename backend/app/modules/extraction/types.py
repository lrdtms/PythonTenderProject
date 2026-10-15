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

    def as_row(self) -> dict[str, Any]:
        return {
            "section": self.section, "item_no": self.item_no, "description": self.description,
            "unit": self.unit, "quantity": self.quantity, "rate": self.rate,
            "raw_unit": self.raw_unit, "raw_quantity": self.raw_quantity, "flags": list(self.flags),
            "page_number": self.page_number, "sheet": self.sheet, "cell_range": self.cell_range,
        }  # fmt: skip


@dataclass
class BoqResult:
    items: list[BoqCandidate] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    boq_pages: set[int] = field(default_factory=set)
