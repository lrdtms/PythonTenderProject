"""Ground-truth data model for synthetic tender packs.

Everything the evaluation needs to score the system is stored here, with the exact
location of each label (physical 1-based page index, or sheet + cell range).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = "1.0"


@dataclass
class Source:
    document: str
    page: int | None = None  # physical 1-based page index (what PDF.js opens)
    printed_page: str | None = None  # label printed on the page, may differ from `page`
    sheet: str | None = None
    cell_range: str | None = None


@dataclass
class Requirement:
    id: str
    description: str
    # deadline|meeting|eligibility|document|pricing|technical|evaluation|other
    requirement_type: str
    mandatory_status: str  # mandatory|conditional|informational
    evidence_quote: str  # verbatim sentence in the source document
    keyword: str  # lower-case phrase a correct extraction must contain
    source: Source


@dataclass
class BoqItem:
    item_number: str
    section: str
    description: str
    unit: str | None  # canonical: m, no, item, sum, m2
    quantity: str | None  # canonical decimal string, None = missing in the source
    unit_price: str | None
    raw_unit: str | None  # exactly as rendered in the document
    raw_quantity: str | None
    flags: list[str]  # missing_quantity, rate_only, provisional_sum, unit_alias, ...
    source: Source


@dataclass
class QuotationItem:
    description: str
    unit: str | None
    quantity: str | None
    unit_price: str | None
    expected_match: str | None  # BoQ item_number a correct matcher confirms, else None
    confusable_with: str | None  # near-identical BoQ item that must NOT be auto-matched
    unit_mismatch: bool
    ambiguous: bool  # a human must confirm
    source: Source


@dataclass
class Quotation:
    supplier: str
    reference: str
    date: str
    valid_until: str
    currency: str
    document: str
    items: list[QuotationItem] = field(default_factory=list)


@dataclass
class Document:
    filename: str
    kind: str  # tender_document | boq | quotation
    format: str  # pdf | xlsx
    scanned: bool = False
    pages: int | None = None


@dataclass
class NonRequirement:
    kind: str  # prompt_injection | boilerplate
    text: str
    source: Source


@dataclass
class Pack:
    pack_id: str
    title: str
    reference: str
    client: str
    location: str
    closing_at: str  # ISO 8601
    tags: list[str]
    documents: list[Document] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    boq_items: list[BoqItem] = field(default_factory=list)
    quotations: list[Quotation] = field(default_factory=list)
    non_requirements: list[NonRequirement] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    synthetic: bool = True

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    def write(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")
