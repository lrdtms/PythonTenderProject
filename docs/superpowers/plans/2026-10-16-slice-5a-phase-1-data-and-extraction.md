# Slice 5a, Phase 1: Data Model and Quotation Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uploading a supplier quotation (PDF or XLSX) produces a stored quotation with its header details, a supplier found or created from the header name, and priced quotation items with sources and flags, through the real worker, with the four Slice 5a tables in place for the later phases.

**Architecture:** A pure `extraction.parse_quotation` core (no I/O) reads the header and the item table, reusing the BoQ parser's table helpers. A new `suppliers` module owns the tables (`suppliers`, `quotations`, `quotation_items`, `match_suggestions`) and the use cases (`store_quotation`). A new `extract_quotation` job type is routed for `quotation` documents, runs through the existing run/lock/lifecycle code in `pipeline`, and appears as a third kind in the extraction status. Matching, the API and the UI are later phases.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, pytest (backend under `backend/`, run with `uv run`); Vitest for the one small frontend change.

**Spec:** `docs/superpowers/specs/2026-10-16-slice-5a-suppliers-matching-design.md` (sections 3 and 4). Later phases: 2 matching, 3 API, 4 comparison UI, 5 suppliers page and gate.

## Global Constraints

- **Module rules (F2, import-linter):** modules import each other only through `public.py`; `app.modules.extraction` and `app.kernel` import neither `sqlalchemy` nor `fastapi`; all queries go through `ScopedRepository` subclasses (`app/db/scoped.py`); handlers in `app/worker/handlers.py` do the cross-module orchestration.
- **Tenancy (F1/F3):** every new table has `organisation_id NOT NULL` and every foreign key to an organisation-owned table is composite and includes `organisation_id`. A referenced table therefore needs a `UNIQUE (organisation_id, id)` (or the wider key the child uses): Task 1 adds one to the existing `boq_items`.
- **Money and numbers:** `Decimal` only, columns `NUMERIC(18,4)`, never `float`. Missing is `NULL` plus a flag, never 0. Use `extraction.numbers.parse_decimal` and `is_ambiguous_separator`. A quotation item without a readable unit price stores `unit_price = NULL` and the flag `price_unparsed` (text present but unreadable) or `missing_price` (no text).
- **Tests:** backend suite stays green: `cd backend && DB_HOST_PORT=5433 uv run pytest -q` (about 2 minutes; run the new test file alone while iterating). Lint: `uv run ruff check . && uv run ruff format --check .` and `uv run lint-imports`. Committed fixtures: `backend/tests/fixtures/packs/pack0{1..4}/` (5 quotations: two PDF, two XLSX across four packs, each with `ground_truth.json`).
- **Shell:** the Bash tool here mishandles long heredocs; create files with the editor tools and run short commands.
- **Branch:** `feat/slice-5a-phase-1-data-extraction` from `main`. Commit messages end with the attribution lines from the session's system reminder (`Co-Authored-By: ...` and `Claude-Session: ...`).

## Review Focus

1. A quotation with no readable header (no supplier name, date, validity or currency): it still stores, using the file name as the supplier name, and every missing header field is flagged, never guessed (Tasks 2, 3).
2. Price cells such as `R 1 234,50`, `1,500`, `POA`, `-`, an empty cell or `12.34567`: parsed or stored as `NULL` with a flag, and never 0 (Task 2).
3. Descriptions wrapped across lines with the SKU on the next line, SKU written as `[SKU-5078]`, `Code: AB-12` or absent, and cells containing newlines (Task 2).
4. A re-run: reviewed items survive, items referenced by a confirmed or rejected match survive, and a supplier the user switched is not switched back (Task 3).
5. A scanned quotation PDF, an XLSX with no table, and a quotation on an archived tender: a warning (`QUOTE_NEEDS_MANUAL_ENTRY`, `NO_QUOTATION_FOUND`) or `TENDER_ARCHIVED`, never a crash or invented rows (Tasks 2, 3).

---

### Task 1: Tables, models and migration 0005

**Files:**
- Create: `backend/app/modules/suppliers/models.py`
- Modify: `backend/app/modules/estimating/models.py` (add one unique constraint), `backend/app/modules/pipeline/models.py` (`RUN_KINDS`)
- Create: `backend/migrations/versions/0005_suppliers_quotations.py`
- Test: `backend/tests/test_suppliers_schema.py`

**Interfaces:**
- Produces ORM classes `Supplier`, `Quotation`, `QuotationItem`, `MatchSuggestion` in `app.modules.suppliers.models`, constants `QUOTATION_REVIEW_STATUSES`, `MATCH_STATUSES = ("suggested", "confirmed", "rejected")`, `MATCH_CLASSIFICATIONS = ("clear", "ambiguous")`; `RUN_KINDS = ("boq", "requirements", "quotation")`.

- [ ] **Step 1: Write the failing schema test**

Create `backend/tests/test_suppliers_schema.py`:

```python
"""The Slice 5a tables: tenancy shape and the constraints later phases rely on."""

from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, Index, UniqueConstraint

from app.db.base import Base
from app.infrastructure.model_registry import import_all_models

import_all_models()

TABLES = ("suppliers", "quotations", "quotation_items", "match_suggestions")


def _table(name: str):
    return Base.metadata.tables[name]


def _unique_sets(table) -> set[frozenset[str]]:
    out = {frozenset(c.name for c in u.columns) for u in table.constraints if isinstance(u, UniqueConstraint)}
    out |= {frozenset(c.name for c in i.columns) for i in table.indexes if i.unique}
    return out


def test_new_tables_exist_and_are_org_owned() -> None:
    for name in TABLES:
        table = _table(name)
        assert "organisation_id" in table.c and not table.c.organisation_id.nullable


def test_parents_can_be_referenced_with_the_organisation() -> None:
    assert frozenset({"organisation_id", "id"}) in _unique_sets(_table("suppliers"))
    assert frozenset({"organisation_id", "id"}) in _unique_sets(_table("quotation_items"))
    assert frozenset({"organisation_id", "id"}) in _unique_sets(_table("boq_items"))
    assert frozenset({"organisation_id", "id", "document_version_id"}) in _unique_sets(_table("quotations"))


def test_supplier_name_is_unique_per_organisation() -> None:
    assert frozenset({"organisation_id", "name_key"}) in _unique_sets(_table("suppliers"))


def test_one_quotation_per_document_version() -> None:
    assert frozenset({"organisation_id", "document_version_id"}) in _unique_sets(_table("quotations"))


def test_a_pair_is_suggested_once() -> None:
    assert frozenset({"boq_item_id", "quotation_item_id"}) in _unique_sets(_table("match_suggestions"))


def test_at_most_one_confirmed_match_per_boq_line_and_supplier() -> None:
    indexes = {i.name: i for i in _table("match_suggestions").indexes}
    index = indexes["uq_match_confirmed_per_boq_supplier"]
    assert index.unique and [c.name for c in index.columns] == ["boq_item_id", "supplier_id"]
    assert "confirmed" in str(index.dialect_options["postgresql"]["where"])


def test_foreign_keys_are_composite() -> None:
    for name in TABLES:
        for fk in (c for c in _table(name).constraints if isinstance(c, ForeignKeyConstraint)):
            if fk.referred_table.name == "organisations":
                continue
            assert "organisation_id" in {c.name for c in fk.columns}, f"{name}: {fk.name}"


def test_quotation_is_an_extraction_run_kind() -> None:
    from app.modules.pipeline.models import RUN_KINDS

    assert "quotation" in RUN_KINDS
```

- [ ] **Step 2: Run it and see it fail**

Run: `cd backend && uv run pytest tests/test_suppliers_schema.py -q`
Expected: FAIL (`KeyError: 'suppliers'` or assertion on missing tables).

- [ ] **Step 3: Add the models**

Create `backend/app/modules/suppliers/models.py` (the package `__init__.py` already exists, one line):

```python
"""Suppliers, their quotations and the match suggestions between quotation items and BoQ lines."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

QUOTATION_REVIEW_STATUSES = ("unreviewed", "confirmed", "corrected", "rejected")
MATCH_STATUSES = ("suggested", "confirmed", "rejected")
MATCH_CLASSIFICATIONS = ("clear", "ambiguous")


def _org_col() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("organisations.id"), nullable=False)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = _org_col()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_key: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_suppliers_org_id"),
        UniqueConstraint("organisation_id", "name_key", name="uq_suppliers_org_name_key"),
    )


class Quotation(Base):
    __tablename__ = "quotations"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = _org_col()
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100))
    quote_date: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    prices_include_vat: Mapped[bool | None] = mapped_column(Boolean)
    flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_quotations_org_id"),
        UniqueConstraint(
            "organisation_id", "id", "document_version_id", name="uq_quotations_org_id_version"
        ),
        UniqueConstraint("organisation_id", "document_version_id", name="uq_quotations_org_version"),
        ForeignKeyConstraint(
            ["organisation_id", "run_id", "document_version_id"],
            [
                "extraction_runs.organisation_id",
                "extraction_runs.id",
                "extraction_runs.document_version_id",
            ],
            name="fk_quotations_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "supplier_id"],
            ["suppliers.organisation_id", "suppliers.id"],
            name="fk_quotations_supplier",
        ),
    )


class QuotationItem(Base):
    __tablename__ = "quotation_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = _org_col()
    quotation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100))
    unit: Mapped[str | None] = mapped_column(String(30))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    raw_unit: Mapped[str | None] = mapped_column(String(50))
    raw_quantity: Mapped[str | None] = mapped_column(String(50))
    raw_price: Mapped[str | None] = mapped_column(String(50))
    flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    page_number: Mapped[int | None] = mapped_column(Integer)
    sheet: Mapped[str | None] = mapped_column(String(200))
    cell_range: Mapped[str | None] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unreviewed")
    original_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    corrected_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_quotation_items_org_id"),
        ForeignKeyConstraint(
            ["organisation_id", "quotation_id", "document_version_id"],
            ["quotations.organisation_id", "quotations.id", "quotations.document_version_id"],
            name="fk_quotation_items_quotation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "run_id", "document_version_id"],
            [
                "extraction_runs.organisation_id",
                "extraction_runs.id",
                "extraction_runs.document_version_id",
            ],
            name="fk_quotation_items_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "reviewed_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_quotation_items_reviewer_membership",
        ),
        Index("ix_quotation_items_version", "document_version_id", "source_order", "position"),
        Index("ix_quotation_items_quotation", "quotation_id"),
    )


class MatchSuggestion(Base):
    __tablename__ = "match_suggestions"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = _org_col()
    boq_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    quotation_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    classification: Mapped[str] = mapped_column(String(10), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="suggested")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("boq_item_id", "quotation_item_id", name="uq_match_pair"),
        CheckConstraint("status IN ('suggested', 'confirmed', 'rejected')", name="ck_match_status"),
        CheckConstraint("classification IN ('clear', 'ambiguous')", name="ck_match_classification"),
        ForeignKeyConstraint(
            ["organisation_id", "boq_item_id"],
            ["boq_items.organisation_id", "boq_items.id"],
            name="fk_match_boq_item",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "quotation_item_id"],
            ["quotation_items.organisation_id", "quotation_items.id"],
            name="fk_match_quotation_item",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "supplier_id"],
            ["suppliers.organisation_id", "suppliers.id"],
            name="fk_match_supplier",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "decided_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_match_decider_membership",
        ),
        Index(
            "uq_match_confirmed_per_boq_supplier",
            "boq_item_id",
            "supplier_id",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
        Index("ix_match_boq_item", "boq_item_id"),
        Index("ix_match_quotation_item", "quotation_item_id"),
    )
```

In `backend/app/modules/estimating/models.py`, add to `BoqItem.__table_args__` (first entry of the tuple):

```python
        UniqueConstraint("organisation_id", "id", name="uq_boq_items_org_id"),
```

and add `UniqueConstraint` to that file's `sqlalchemy` import list. In `backend/app/modules/pipeline/models.py` change `RUN_KINDS = ("boq", "requirements")` to `RUN_KINDS = ("boq", "requirements", "quotation")`.

- [ ] **Step 4: Generate and review the migration**

Run (dev database from the Docker stack; port 5433):

```bash
cd backend
DB_HOST_PORT=5433 uv run alembic upgrade head
DB_HOST_PORT=5433 uv run alembic revision --autogenerate --rev-id 0005 -m "suppliers quotations"
```

Rename the generated file to `migrations/versions/0005_suppliers_quotations.py` and open it. It must: create the four tables with the constraints and indexes above (including the partial unique index `uq_match_confirmed_per_boq_supplier` with `postgresql_where=sa.text("status = 'confirmed'")`), `op.create_unique_constraint('uq_boq_items_org_id', 'boq_items', ['organisation_id', 'id'])`, and a `downgrade()` that drops them in reverse order (`match_suggestions`, `quotation_items`, `quotations`, `suppliers`, then the boq_items constraint). Fix anything autogenerate got wrong (it often misses `postgresql_where`). Follow the style of `0004_source_order.py` (plain `op.` calls, `revision = '0005'`, `down_revision = '0004'`).

- [ ] **Step 5: Run the schema test and the migration check**

Run: `cd backend && DB_HOST_PORT=5433 uv run pytest tests/test_suppliers_schema.py tests/test_fitness_functions.py -q`
Expected: PASS (`test_migrations_match_the_models` proves the migration and the models agree; the F3 tests prove the tenancy shape).

- [ ] **Step 6: Lint and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
git add -A && git commit -m "feat: suppliers, quotations, quotation items and match suggestions tables"
```

(Append the attribution lines to the commit message.)

---

### Task 2: `parse_quotation` (pure core)

**Files:**
- Modify: `backend/app/modules/extraction/types.py`, `backend/app/modules/extraction/public.py`
- Create: `backend/app/modules/extraction/quotation.py`
- Test: `backend/tests/test_quotation_parser.py`

**Interfaces:**
- Consumes: `PageInput`, `source_order`, `canon_unit`, `parse_decimal`, `is_ambiguous_separator`, and from `boq.py`: `_norm`, `_get`, `_column_letter`, `SUBTOTAL`, `TOTAL_WORD`, `PROVISIONAL` (importing them within the same package is fine).
- Produces (exported from `extraction.public`):
  - `QuotationHeader` dataclass: `supplier_name: str | None`, `reference: str | None`, `quote_date: date | None`, `valid_until: date | None`, `currency: str | None`, `prices_include_vat: bool | None`, `flags: list[str]`; method `as_row() -> dict` (dates as ISO strings or `None`).
  - `QuotationCandidate` dataclass: `description`, `sku`, `unit`, `quantity: Decimal | None`, `unit_price: Decimal | None`, `raw_unit`, `raw_quantity`, `raw_price`, `flags: list[str]`, `page_number`, `sheet`, `cell_range`, `source_order`; method `as_row() -> dict`.
  - `QuotationResult` dataclass: `header: QuotationHeader`, `items: list[QuotationCandidate]`, `warnings: list[dict]`, `quote_pages: set[int]`.
  - `parse_quotation(pages: Sequence[PageInput]) -> QuotationResult`.
  - `QUOTATION_TEXT_LIMITS` mapping (column widths from Task 1) used for clipping with the `truncated` flag.

Header flags (also copied into `warnings` as `{"code": flag}` by the handler in Task 3): `NO_SUPPLIER_NAME`, `NO_REFERENCE`, `NO_QUOTE_DATE`, `NO_VALIDITY`, `NO_CURRENCY`, `VAT_UNKNOWN`. Result warnings: `QUOTE_NEEDS_MANUAL_ENTRY` (`pages`) for a scanned quotation, `NO_QUOTATION_FOUND` when no item table was found.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_quotation_parser.py`. It builds `PageInput`s by hand for the messy cases and scores the five committed quotations against their ground truth:

```python
"""Quotation parsing: header, items, SKUs, prices, and the committed ground truth."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.extraction import public as extraction
from app.modules.knowledge.parsers import parse_document

PACKS = Path(__file__).parent / "fixtures" / "packs"
HEADER = ["#", "Description", "Unit", "Qty", "Unit price"]


def page(text: str, rows: list[list[str]], number: int = 1, source: str = "embedded", kind: str = "table"):
    table = {"kind": kind, "rows": rows}
    if kind == "sheet":
        table["first_row"] = 1
    return extraction.PageInput(number, "Quote 1" if kind == "sheet" else None, text, source, "ok", [table])


def parse(rows, text="ACME SUPPLIES\nQUOTATION Q1\nDate: 2026-10-20", **kw):
    return extraction.parse_quotation([page(text, rows, **kw)])


def test_reads_the_pdf_style_header() -> None:
    text = (
        "Synthetic test document - fictional data\nPage 1\nSPARKMORE SUPPLIES\nQUOTATION Q33227\n"
        "Date: 2026-10-20    Valid until: 2026-11-26    Currency: ZAR\n"
        "Prices exclude value-added tax unless stated. Subject to availability of stock.\n"
        "#\nDescription\nUnit\nQty\nUnit price\n"
    )
    h = parse([HEADER, ["1", "Cable", "m", "10", "5.00"]], text).header
    assert h.supplier_name == "SPARKMORE SUPPLIES"
    assert (h.reference, h.quote_date, h.valid_until, h.currency) == (
        "Q33227", date(2026, 10, 20), date(2026, 11, 26), "ZAR")
    assert h.prices_include_vat is False and h.flags == []


def test_reads_the_sheet_style_header_from_the_rows_above_the_table() -> None:
    rows = [["Greenvale Cable and Conduit"], ["Quotation Q78533"], ["Date: 2026-10-21"],
            ["Valid until: 2026-11-12"], ["Currency: ZAR"], [], HEADER, ["1", "Socket", "no", "43", "146"]]
    result = extraction.parse_quotation([page("", rows, kind="sheet")])
    h = result.header
    assert (h.supplier_name, h.reference, h.valid_until, h.currency) == (
        "Greenvale Cable and Conduit", "Q78533", date(2026, 11, 12), "ZAR")
    assert h.prices_include_vat is None and "VAT_UNKNOWN" in h.flags
    assert result.items[0].cell_range == "A8:E8" and result.items[0].sheet == "Quote 1"


def test_missing_header_fields_are_flagged_not_guessed() -> None:
    h = parse([HEADER, ["1", "Cable", "m", "10", "5"]], text="").header
    assert h.supplier_name is None and h.reference is None and h.currency is None
    assert {"NO_SUPPLIER_NAME", "NO_REFERENCE", "NO_QUOTE_DATE", "NO_VALIDITY", "NO_CURRENCY",
            "VAT_UNKNOWN"} <= set(h.flags)


def test_sku_is_lifted_out_of_a_wrapped_description() -> None:
    item = parse([HEADER, ["1", "Main board, 400 A\n[SKU-5078]", "no", "2", "54917.00"]]).items[0]
    assert item.sku == "SKU-5078" and item.description == "Main board, 400 A"


@pytest.mark.parametrize("cell, sku", [("LED panel Code: AB-12", "AB-12"), ("LED panel [ab-12]", "ab-12"),
                                       ("LED panel (not a code)", None), ("LED panel", None)])
def test_sku_variants(cell: str, sku: str | None) -> None:
    assert parse([HEADER, ["1", cell, "no", "1", "5"]]).items[0].sku == sku


@pytest.mark.parametrize("raw, price, flag", [
    ("5.00", Decimal("5.00"), None), ("R 1 234,50", Decimal("1234.50"), None),
    ("1,500", Decimal("1500"), "ambiguous_separator"), ("POA", None, "price_unparsed"),
    ("-", None, "missing_price"), ("", None, "missing_price"), ("12.34567", None, "price_unparsed")])
def test_prices_are_parsed_or_null_never_zero(raw: str, price: Decimal | None, flag: str | None) -> None:
    item = parse([HEADER, ["1", "Cable", "m", "10", raw]]).items[0]
    assert item.unit_price == price
    if price is None:
        assert item.unit_price != Decimal(0)
    assert (flag in item.flags) if flag else not set(item.flags) & {"price_unparsed", "missing_price"}


def test_quantity_missing_or_unreadable_is_flagged() -> None:
    items = parse([HEADER, ["1", "A", "m", "", "5"], ["2", "B", "m", "ten", "5"]]).items
    assert "missing_quantity" in items[0].flags and items[0].quantity is None
    assert "quantity_unparsed" in items[1].flags and items[1].quantity is None


def test_unit_is_canonical_and_alias_flagged() -> None:
    item = parse([HEADER, ["1", "Cable", "Metres", "10", "5"]]).items[0]
    assert item.unit == "m" and "unit_alias" in item.flags and item.raw_unit == "Metres"


def test_totals_and_blank_rows_are_not_items() -> None:
    rows = [HEADER, ["1", "Cable", "m", "10", "5"], [], ["", "Sub-total", "", "", "50"], ["", "Total", "", "", "50"]]
    assert [i.description for i in parse(rows).items] == ["Cable"]


def test_a_table_continues_on_the_next_page_without_a_header() -> None:
    first = page("ACME\nQUOTATION Q1", [HEADER, ["1", "A", "m", "1", "1"]], number=1)
    second = extraction.PageInput(2, None, "", "embedded", "ok", [{"kind": "table", "rows": [["2", "B", "m", "2", "2"]]}])
    result = extraction.parse_quotation([first, second])
    assert [(i.description, i.page_number) for i in result.items] == [("A", 1), ("B", 2)]


def test_scanned_quotation_is_flagged_for_manual_entry() -> None:
    text = "ACME\nQUOTATION\n# Description Unit Qty Unit price\n1 Cable m 10 5.00"
    scanned = extraction.PageInput(1, None, text, "ocr", "ok", [])
    result = extraction.parse_quotation([scanned])
    assert result.items == [] and result.warnings == [{"code": "QUOTE_NEEDS_MANUAL_ENTRY", "pages": [1]}]


def test_no_table_gives_a_warning_not_an_error() -> None:
    result = extraction.parse_quotation([extraction.PageInput(1, None, "Dear sir", "embedded", "ok", [])])
    assert result.items == [] and result.warnings == [{"code": "NO_QUOTATION_FOUND"}]


def test_oversized_cells_are_clipped_and_flagged() -> None:
    item = parse([HEADER, ["1", "Cable [" + "X" * 300 + "]", "m" * 60, "1", "1"]]).items[0]
    assert "truncated" in item.flags and len(item.raw_unit or "") <= 50


# --- scoring against the committed ground truth ------------------------------------------------


def _norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _sku(description: str) -> str | None:
    found = re.search(r"\[(SKU-[\w-]+)\]", description)
    return found.group(1).lower() if found else None


def _quotations():
    for pack in sorted(PACKS.iterdir()):
        truth = json.loads((pack / "ground_truth.json").read_text(encoding="utf-8"))
        for quote in truth["quotations"]:
            yield pytest.param(pack, quote, id=f"{pack.name}/{quote['document']}")


@pytest.mark.parametrize("pack, quote", list(_quotations()))
def test_parser_reads_every_committed_quotation(pack: Path, quote: dict) -> None:
    doc = next(d for d in json.loads((pack / "ground_truth.json").read_text())["documents"]
               if d["filename"] == quote["document"])
    pages = [extraction.PageInput(p.page_number, p.label, p.text, p.text_source, p.status, p.tables)
             for p in parse_document(doc["format"], (pack / quote["document"]).read_bytes())]
    result = extraction.parse_quotation(pages)
    header = result.header
    assert _norm(header.supplier_name) == _norm(quote["supplier"])
    assert header.reference == quote["reference"]
    assert header.quote_date == date.fromisoformat(quote["date"])
    assert header.valid_until == date.fromisoformat(quote["valid_until"])
    assert header.currency == quote["currency"]
    by_sku = {i.sku.lower(): i for i in result.items if i.sku}
    assert len(result.items) == len(quote["items"])
    for truth in quote["items"]:
        got = by_sku[_sku(truth["description"])]
        assert got.unit == truth["unit"]
        assert got.quantity == Decimal(truth["quantity"])
        assert got.unit_price == Decimal(truth["unit_price"])
        assert _norm(truth["description"].split(" [SKU")[0]) == _norm(got.description)
```

- [ ] **Step 2: Run and see it fail**

Run: `cd backend && uv run pytest tests/test_quotation_parser.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'parse_quotation'`).

- [ ] **Step 3: Add the types**

Append to `backend/app/modules/extraction/types.py` (add `from datetime import date` to its imports):

```python
# Column widths of quotation_items (migration 0005); the parser clips to these and flags `truncated`.
QUOTATION_TEXT_LIMITS: dict[str, int] = {
    "sku": 100, "unit": 30, "raw_unit": 50, "raw_quantity": 50, "raw_price": 50,
    "sheet": 200, "cell_range": 40,
}  # fmt: skip


@dataclass
class QuotationHeader:
    supplier_name: str | None = None
    reference: str | None = None
    quote_date: date | None = None
    valid_until: date | None = None
    currency: str | None = None
    prices_include_vat: bool | None = None
    flags: list[str] = field(default_factory=list)

    def as_row(self) -> dict[str, Any]:
        return {
            "supplier_name": self.supplier_name, "reference": self.reference,
            "quote_date": self.quote_date.isoformat() if self.quote_date else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "currency": self.currency, "prices_include_vat": self.prices_include_vat,
            "flags": list(self.flags),
        }  # fmt: skip


@dataclass
class QuotationCandidate:
    description: str
    sku: str | None
    unit: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    raw_unit: str | None
    raw_quantity: str | None
    raw_price: str | None
    flags: list[str]
    page_number: int | None
    sheet: str | None
    cell_range: str | None
    source_order: int = 0

    def as_row(self) -> dict[str, Any]:
        return {
            "description": self.description, "sku": self.sku, "unit": self.unit,
            "quantity": self.quantity, "unit_price": self.unit_price, "raw_unit": self.raw_unit,
            "raw_quantity": self.raw_quantity, "raw_price": self.raw_price,
            "flags": list(self.flags), "page_number": self.page_number, "sheet": self.sheet,
            "cell_range": self.cell_range, "source_order": self.source_order,
        }  # fmt: skip


@dataclass
class QuotationResult:
    header: QuotationHeader = field(default_factory=QuotationHeader)
    items: list[QuotationCandidate] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    quote_pages: set[int] = field(default_factory=set)
```

- [ ] **Step 4: Implement the parser**

Create `backend/app/modules/extraction/quotation.py`:

```python
"""Deterministic quotation extraction from ingested pages (no LLM, FR-55)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from .boq import PROVISIONAL, SUBTOTAL, TOTAL_WORD, _column_letter, _get, _norm
from .numbers import is_ambiguous_separator, parse_decimal
from .types import (
    QUOTATION_TEXT_LIMITS,
    PageInput,
    QuotationCandidate,
    QuotationHeader,
    QuotationResult,
    source_order,
)
from .units import canon_unit

HEADER_WORDS = {
    "item": {"#", "item", "item no", "item no.", "no", "no.", "line", "ref", "nr"},
    "description": {"description", "details", "item description", "product", "particulars"},
    "unit": {"unit", "units", "uom"},
    "quantity": {"qty", "qty.", "quantity", "quantities"},
    "price": {
        "unit price", "price", "rate", "price each", "unit rate", "nett price", "net price",
        "unit price (r)", "price (r)", "rate (r)",
    },
    "amount": {"amount", "total", "line total", "amount (r)", "total (r)", "extended price"},
}  # fmt: skip
MAX_HEADER_SEARCH_ROWS = 60

_DATE = r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
QUOTE_DATE = re.compile(r"(?<![a-z])date\s*[:\-]?\s*" + _DATE, re.I)
VALID_UNTIL = re.compile(r"valid(?:ity)?\s*(?:until|to|till|through)?\s*[:\-]?\s*" + _DATE, re.I)
REFERENCE = re.compile(
    r"\b(?:quotation|quote)\s*(?:no\.?|number|ref\.?|#)?\s*[:\-]?\s*([A-Za-z]*\d[\w\-/]*)", re.I
)
CURRENCY = re.compile(r"currency\s*[:\-]?\s*([A-Z]{3})\b|\b(ZAR)\b")
VAT_EXCLUDED = re.compile(r"\b(?:exclud\w*|excl\.?|ex\.?)\s*(?:of\s*)?(?:value[- ]added tax|vat)", re.I)
VAT_INCLUDED = re.compile(r"\b(?:includ\w*|incl\.?)\s*(?:of\s*)?(?:value[- ]added tax|vat)", re.I)
NOT_A_NAME = re.compile(
    r"synthetic test|^page\s*\d+|^\s*quotation\b|^\s*quote\b|^\s*date\b|valid|currency|^\s*prices?\b|"
    r"subject to|^\s*(tel|phone|email|e-mail|fax|www)\b|@|vat\s*(no|number|reg)|^\s*(to|attn|attention)\b",
    re.I,
)
BRACKET_SKU = re.compile(r"\[\s*((?:SKU[\s:\-]*)?[A-Za-z0-9][A-Za-z0-9\-_/.]{1,40})\s*\]\s*$", re.I)
LABEL_SKU = re.compile(r"\b(?:sku|code|part\s*no\.?|product\s*code)\s*[:#]\s*([A-Za-z0-9][\w\-/.]{1,40})\s*$", re.I)


def _parse_date(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _find_header(rows: Sequence[Sequence[str]]) -> tuple[int, dict[str, int]] | None:
    for index, row in enumerate(rows[:MAX_HEADER_SEARCH_ROWS]):
        columns: dict[str, int] = {}
        for position, cell in enumerate(row):
            key = _norm(cell)
            for field, words in HEADER_WORDS.items():
                if key in words and field not in columns:
                    columns[field] = position
        if "description" in columns and "price" in columns and len(columns) >= 3:
            return index, columns
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _lift_sku(description: str) -> tuple[str, str | None]:
    """Split a trailing product code off the description: `[SKU-5078]`, `[ab-12]` or `Code: X`."""
    text = _clean(description)
    for pattern in (BRACKET_SKU, LABEL_SKU):
        found = pattern.search(text)
        if found and re.search(r"\d", found.group(1)):
            return text[: found.start()].strip(" ,;-"), found.group(1).strip()
    return text, None


def _preamble_lines(page: PageInput, rows: list[list[str]], header_row: int, table: dict) -> list[str]:
    """Text above the item table: the rows above it on a sheet, the page text before the column
    headings on a PDF."""
    if table.get("kind") == "sheet":
        return [_clean(" ".join(str(c) for c in row if str(c or "").strip())) for row in rows[:header_row]]
    lines = [_clean(line) for line in page.text.splitlines()]
    for index, line in enumerate(lines):
        if _norm(line) in HEADER_WORDS["item"] | HEADER_WORDS["description"]:
            return lines[:index]
    return lines


def _read_header(lines: list[str]) -> QuotationHeader:
    header = QuotationHeader()
    blob = "\n".join(line for line in lines if line)
    name = next((line for line in lines if line and re.search(r"[^\W\d_]", line)
                 and not NOT_A_NAME.search(line) and len(line) <= 120), None)
    header.supplier_name = name
    ref = REFERENCE.search(blob)
    header.reference = ref.group(1) if ref else None
    dated = QUOTE_DATE.search(blob)
    header.quote_date = _parse_date(dated.group(1)) if dated else None
    valid = VALID_UNTIL.search(blob)
    header.valid_until = _parse_date(valid.group(1)) if valid else None
    money = CURRENCY.search(blob)
    header.currency = (money.group(1) or money.group(2)) if money else None
    if VAT_EXCLUDED.search(blob):
        header.prices_include_vat = False
    elif VAT_INCLUDED.search(blob):
        header.prices_include_vat = True
    for field, flag in (
        (header.supplier_name, "NO_SUPPLIER_NAME"), (header.reference, "NO_REFERENCE"),
        (header.quote_date, "NO_QUOTE_DATE"), (header.valid_until, "NO_VALIDITY"),
        (header.currency, "NO_CURRENCY"), (header.prices_include_vat, "VAT_UNKNOWN"),
    ):  # fmt: skip
        if field is None:
            header.flags.append(flag)
    return header


def _clip(cand: QuotationCandidate) -> None:
    clipped = False
    for name, limit in QUOTATION_TEXT_LIMITS.items():
        value = getattr(cand, name)
        if isinstance(value, str) and len(value) > limit:
            setattr(cand, name, value[:limit])
            clipped = True
    if clipped:
        cand.flags.append("truncated")


def _candidate(row, columns, page, table, row_index, width, order) -> QuotationCandidate:
    description, sku = _lift_sku(_get(row, columns, "description"))
    raw_unit = _get(row, columns, "unit") or None
    raw_quantity = _get(row, columns, "quantity") or None
    raw_price = _get(row, columns, "price") or None
    flags: list[str] = []
    unit = canon_unit(raw_unit)
    if raw_unit and _norm(raw_unit) != unit:
        flags.append("unit_alias")
    quantity = None
    if raw_quantity:
        quantity, _ = parse_decimal(raw_quantity)
        if quantity is None:
            flags.append("quantity_unparsed")
    else:
        flags.append("missing_quantity")
    price = None
    if raw_price and _norm(raw_price) not in {"-", "–", "—"}:
        price, _ = parse_decimal(raw_price)
        if price is None:
            flags.append("price_unparsed")
    else:
        flags.append("missing_price")
    if is_ambiguous_separator(raw_quantity) or is_ambiguous_separator(raw_price):
        flags.append("ambiguous_separator")
    if PROVISIONAL.search(description):
        flags.append("provisional_sum")
    sheet = cell_range = page_number = None
    if table.get("kind") == "sheet":
        sheet = page.label
        excel_row = int(table.get("first_row", 1)) + row_index
        cell_range = f"A{excel_row}:{_column_letter(width - 1)}{excel_row}"
    else:
        page_number = page.page_number
    cand = QuotationCandidate(
        description=description, sku=sku, unit=unit, quantity=quantity, unit_price=price,
        raw_unit=raw_unit, raw_quantity=raw_quantity, raw_price=raw_price, flags=flags,
        page_number=page_number, sheet=sheet, cell_range=cell_range, source_order=order,
    )  # fmt: skip
    _clip(cand)
    return cand


def parse_quotation(pages: Sequence[PageInput]) -> QuotationResult:
    result = QuotationResult()
    header_read = False
    carried: tuple[dict[str, int], int] | None = None
    last_page: int | None = None
    scanned: list[int] = []
    for page in pages:
        if carried is not None and (last_page is None or page.page_number not in (last_page, last_page + 1)):
            carried = None
        if page.text_source == "ocr" and not page.tables:
            words = set(re.findall(r"[a-z]+", page.text.lower()))
            hits = sum(1 for f in ("description", "unit", "quantity", "price") if HEADER_WORDS[f] & words)
            if hits >= 3:
                scanned.append(page.page_number)
            continue
        for table_idx, table in enumerate(page.tables):
            rows = [list(r) for r in table.get("rows", [])]
            if not rows:
                continue
            found = _find_header(rows)
            if found is not None:
                start, columns = found
                width = max(max(columns.values()) + 1, len(rows[start]))
                carried = (columns, width)
                last_page = page.page_number
                body_from = start + 1
                if not header_read:
                    result.header = _read_header(_preamble_lines(page, rows, start, table))
                    header_read = True
            elif carried is not None and table.get("kind") != "sheet":
                columns, width = carried
                if max(len(r) for r in rows) < width:
                    carried = None
                    continue
                last_page = page.page_number
                body_from = 0
            else:
                continue
            for offset, row in enumerate(rows[body_from:], start=body_from):
                if not any(str(c or "").strip() for c in row):
                    continue
                description = _get(row, columns, "description")
                if not description or SUBTOTAL.match(description):
                    continue
                if TOTAL_WORD.match(description) and not (_get(row, columns, "unit") or _get(row, columns, "quantity")):
                    continue
                if not any(_get(row, columns, f) for f in ("unit", "quantity", "price")):
                    continue  # a heading line inside the table
                result.items.append(
                    _candidate(row, columns, page, table, offset, width,
                               source_order(page.page_number, table_idx * 10_000 + offset))
                )
                result.quote_pages.add(page.page_number)
    if not header_read:
        result.header = _read_header([])
    if scanned:
        result.warnings.append({"code": "QUOTE_NEEDS_MANUAL_ENTRY", "pages": scanned})
    elif not result.items:
        result.warnings.append({"code": "NO_QUOTATION_FOUND"})
    return result
```

Note: `quote_date` flag logic reads `header.quote_date`; the `NOT_A_NAME` list is deliberately conservative. If a ground-truth supplier name is rejected by it, widen the *allow* side (not the deny list) and add a test.

In `backend/app/modules/extraction/public.py` add the imports and `__all__` entries: `from .quotation import parse_quotation`, and from `.types` import `QUOTATION_TEXT_LIMITS, QuotationCandidate, QuotationHeader, QuotationResult`.

- [ ] **Step 5: Run the tests; fix until green**

Run: `cd backend && uv run pytest tests/test_quotation_parser.py -q`
Expected: PASS. If the ground-truth test fails on a particular quotation, print the parsed header/items for that file, fix the parser generally (not for the one file), and keep the test as written. Likely adjustments: header synonyms, `NOT_A_NAME`, trailing-SKU handling when a cell has the SKU in the middle.

- [ ] **Step 6: Lint, import rules and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
git add -A && git commit -m "feat: deterministic quotation parser"
```

---

### Task 3: Suppliers module, job wiring and the end-to-end pipeline

**Files:**
- Create: `backend/app/modules/suppliers/repo.py`, `schemas.py`, `service.py`, `public.py`
- Modify: `backend/app/modules/documents/service.py` and `public.py` (job constant), `backend/app/modules/pipeline/routing.py`, `backend/app/worker/handlers.py`
- Test: `backend/tests/test_suppliers_store.py`, `backend/tests/test_quotation_pipeline.py`

**Interfaces:**
- Consumes: Task 1 models, Task 2 `QuotationHeader.as_row()` / `QuotationCandidate.as_row()` dictionaries.
- Produces:
  - `documents.EXTRACT_QUOTATION_JOB = "extract_quotation"`; `EXTRACTION_JOBS` includes it; `pipeline.ROUTING["quotation"] = (EXTRACT_QUOTATION_JOB,)`; `KIND_OF_JOB[EXTRACT_QUOTATION_JOB] = "quotation"`.
  - `suppliers.normalise_name(name: str) -> str` (the `name_key`).
  - `suppliers.store_quotation(session, ctx, version_id, run_id, header: Mapping, rows: Sequence[Mapping], fallback_name: str) -> StoreResult` where `StoreResult(inserted: int, duplicates_of_reviewed: int, supplier_id: UUID, quotation_id: UUID, supplier_created: bool)`.
  - `suppliers.public` exports `normalise_name`, `store_quotation`, `StoreResult`.
  - Worker handler `extract_quotation` registered in `HANDLERS`.

- [ ] **Step 1: Write the failing store tests**

Create `backend/tests/test_suppliers_store.py`. These drive `store_quotation` directly against a real version and run created by a BoQ upload helper (use `tests.review_helpers.boq_version` to get an organisation, tender and version, then create the run by hand as `seed_review_rows` does):

```python
"""store_quotation: supplier find-or-create, re-runs, and what a re-run must never delete."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import session_scope
from app.kernel import OrgContext, Role
from app.modules.suppliers import public as suppliers
from app.modules.suppliers.models import MatchSuggestion, Quotation, QuotationItem, Supplier
from tests.conftest import register
from tests.quotation_helpers import quotation_context  # created in Step 3

HEADER = {"supplier_name": "SPARKMORE SUPPLIES", "reference": "Q1", "quote_date": "2026-10-20",
          "valid_until": "2026-11-26", "currency": "ZAR", "prices_include_vat": False, "flags": []}


def row(description: str, sku: str | None = None, price: str = "5.00", order: int = 0) -> dict:
    return {"description": description, "sku": sku, "unit": "m", "quantity": Decimal("10"),
            "unit_price": Decimal(price), "raw_unit": "m", "raw_quantity": "10", "raw_price": price,
            "flags": [], "page_number": 1, "sheet": None, "cell_range": None, "source_order": order}


def test_creates_the_supplier_quotation_and_items() -> None:
    with quotation_context() as q:
        out = suppliers.store_quotation(q.session, q.ctx, q.version_id, q.run_id, HEADER,
                                        [row("Cable A", "SKU-1"), row("Cable B", "SKU-2", order=1)], "file")
        assert (out.inserted, out.duplicates_of_reviewed, out.supplier_created) == (2, 0, True)
        supplier = q.session.get(Supplier, out.supplier_id)
        assert supplier.name == "Sparkmore Supplies" and supplier.name_key == "sparkmore supplies"
        quotation = q.session.get(Quotation, out.quotation_id)
        assert (quotation.reference, str(quotation.valid_until), quotation.currency) == ("Q1", "2026-11-26", "ZAR")
        assert quotation.prices_include_vat is False


def test_normalise_name_ignores_case_punctuation_and_company_suffixes() -> None:
    assert suppliers.normalise_name("Sparkmore Supplies (Pty) Ltd.") == suppliers.normalise_name("SPARKMORE SUPPLIES")


def test_no_supplier_name_falls_back_to_the_file_name_and_is_flagged() -> None:
    with quotation_context() as q:
        out = suppliers.store_quotation(q.session, q.ctx, q.version_id, q.run_id,
                                        {**HEADER, "supplier_name": None, "flags": ["NO_SUPPLIER_NAME"]},
                                        [row("Cable A")], "quote from acme")
        assert q.session.get(Supplier, out.supplier_id).name == "Quote From Acme"
        assert "NO_SUPPLIER_NAME" in q.session.get(Quotation, out.quotation_id).flags


def test_the_same_supplier_name_in_another_quotation_reuses_the_supplier() -> None:
    with quotation_context(versions=2) as q:
        a = suppliers.store_quotation(q.session, q.ctx, q.versions[0], q.runs[0], HEADER, [row("A")], "f")
        b = suppliers.store_quotation(q.session, q.ctx, q.versions[1], q.runs[1],
                                      {**HEADER, "supplier_name": "Sparkmore Supplies Pty Ltd"}, [row("A")], "f")
        assert a.supplier_id == b.supplier_id and not b.supplier_created


def test_a_rerun_replaces_unreviewed_items_and_keeps_the_users_supplier() -> None:
    with quotation_context() as q:
        first = suppliers.store_quotation(q.session, q.ctx, q.version_id, q.run_id, HEADER, [row("Old", "SKU-1")], "f")
        other = Supplier(organisation_id=q.ctx.organisation_id, name="Another", name_key="another")
        q.session.add(other)
        q.session.flush()
        q.session.get(Quotation, first.quotation_id).supplier_id = other.id  # the user switched it
        q.session.flush()
        again = suppliers.store_quotation(q.session, q.ctx, q.version_id, q.run_id, HEADER, [row("New", "SKU-9")], "f")
        assert again.quotation_id == first.quotation_id and again.supplier_id == other.id
        assert [i.description for i in q.items()] == ["New"]


def test_a_rerun_keeps_reviewed_items_and_skips_their_duplicates() -> None:
    with quotation_context() as q:
        suppliers.store_quotation(q.session, q.ctx, q.version_id, q.run_id, HEADER, [row("Kept", "SKU-1")], "f")
        item = q.items()[0]
        item.review_status = "confirmed"
        item.original_value = {"sku": "SKU-1", "description": "Kept", "unit": "m"}
        q.session.flush()
        out = suppliers.store_quotation(q.session, q.ctx, q.version_id, q.run_id, HEADER,
                                        [row("Kept", "SKU-1"), row("Extra", "SKU-2")], "f")
        assert out.duplicates_of_reviewed == 1 and out.inserted == 1
        assert sorted(i.description for i in q.items()) == ["Extra", "Kept"]


def test_a_rerun_keeps_an_item_that_a_decided_match_refers_to() -> None:
    with quotation_context(with_boq=True) as q:
        suppliers.store_quotation(q.session, q.ctx, q.version_id, q.run_id, HEADER, [row("Pinned", "SKU-1")], "f")
        item = q.items()[0]
        q.session.add(MatchSuggestion(organisation_id=q.ctx.organisation_id, boq_item_id=q.boq_item_id, quotation_item_id=item.id,
                                      supplier_id=q.session.get(Quotation, item.quotation_id).supplier_id,
                                      score=Decimal("0.9"), classification="clear", status="rejected"))
        q.session.flush()
        suppliers.store_quotation(q.session, q.ctx, q.version_id, q.run_id, HEADER, [row("Fresh", "SKU-2")], "f")
        assert "Pinned" in [i.description for i in q.items()]


def test_database_allows_one_confirmed_match_per_boq_line_and_supplier() -> None:
    with quotation_context(with_boq=True) as q:
        out = suppliers.store_quotation(q.session, q.ctx, q.version_id, q.run_id, HEADER,
                                        [row("A", "SKU-1"), row("B", "SKU-2", order=1)], "f")
        a, b = q.items()
        q.session.add(MatchSuggestion(organisation_id=q.ctx.organisation_id, boq_item_id=q.boq_item_id, quotation_item_id=a.id, supplier_id=out.supplier_id,
                                      score=Decimal("0.9"), classification="clear", status="confirmed"))
        q.session.flush()
        q.session.add(MatchSuggestion(organisation_id=q.ctx.organisation_id, boq_item_id=q.boq_item_id, quotation_item_id=b.id, supplier_id=out.supplier_id,
                                      score=Decimal("0.8"), classification="clear", status="rejected"))
        q.session.flush()  # a rejected sibling is fine
        q.session.add(MatchSuggestion(organisation_id=q.ctx.organisation_id, boq_item_id=q.boq_item_id, quotation_item_id=b.id, supplier_id=out.supplier_id,
                                      score=Decimal("0.8"), classification="clear", status="confirmed"))
        with pytest.raises(IntegrityError):
            q.session.flush()
```

- [ ] **Step 2: Write the shared test helper**

Create `backend/tests/quotation_helpers.py`:

```python
"""A real organisation with quotation documents and extraction runs, for store and matching tests.

The quotation documents are uploaded but not drained, so the worker never runs `extract_quotation`
on them: the tests call `store_quotation` themselves. Each version gets a `quotation` run that
borrows the ingest job's id (the (job_id, kind) pair is free), as `seed_review_rows` does."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.kernel import OrgContext, Role
from app.modules.estimating.models import BoqItem
from app.modules.pipeline.models import ExtractionRun
from app.modules.suppliers.models import QuotationItem
from tests.conftest import make_tender, make_xlsx, register, upload
from tests.review_helpers import boq_version

QUOTE_ROWS = [["#", "Description", "Unit", "Qty", "Unit price"], ["1", "Cable", "m", "10", "5"]]


@dataclass
class QuotationContext:
    session: Session
    ctx: OrgContext
    versions: list[UUID]
    runs: list[UUID]
    boq_item_id: UUID | None

    @property
    def version_id(self) -> UUID:
        return self.versions[0]

    @property
    def run_id(self) -> UUID:
        return self.runs[0]

    def items(self) -> list[QuotationItem]:
        """Quotation items of the first version, in order."""
        stmt = (
            select(QuotationItem)
            .where(QuotationItem.document_version_id == self.version_id)
            .order_by(QuotationItem.position)
        )
        return list(self.session.scalars(stmt))


@contextmanager
def quotation_context(versions: int = 1, with_boq: bool = False) -> Iterator[QuotationContext]:
    actor = register("store@example.com")
    if with_boq:
        actor, tender_id, _ = boq_version(actor)  # drains: BoQ ingest and extraction run now
    else:
        tender_id = make_tender(actor)
    uploads = [
        upload(actor, tender_id, make_xlsx(QUOTE_ROWS), f"quote{n}.xlsx", kind="quotation").json()
        for n in range(versions)
    ]
    ctx = OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)
    with session_scope() as session:
        version_ids, run_ids = [], []
        for body in uploads:
            run = ExtractionRun(
                organisation_id=ctx.organisation_id,
                document_version_id=UUID(body["version"]["id"]),
                job_id=UUID(body["job_id"]),
                kind="quotation",
            )
            session.add(run)
            session.flush()
            version_ids.append(run.document_version_id)
            run_ids.append(run.id)
        boq_item_id = session.scalar(
            select(BoqItem.id).where(BoqItem.organisation_id == ctx.organisation_id)
        )
        yield QuotationContext(session, ctx, version_ids, run_ids, boq_item_id)
```

In the tests of Step 1, rows added by hand must carry the organisation: write `Supplier(organisation_id=q.ctx.organisation_id, name="Another", name_key="another")` and add `organisation_id=q.ctx.organisation_id` to each `MatchSuggestion(...)` constructor.

- [ ] **Step 3: Run the store tests and see them fail**

Run: `cd backend && DB_HOST_PORT=5433 uv run pytest tests/test_suppliers_store.py -q`
Expected: FAIL (`ImportError`/`AttributeError`: `store_quotation` missing).

- [ ] **Step 4: Implement repo, schemas, service, public**

`backend/app/modules/suppliers/repo.py`: `SupplierRepo`, `QuotationRepo`, `QuotationItemRepo`, `MatchRepo`, each `ScopedRepository` subclasses (pattern of `estimating/repo.py`). Required methods: `SupplierRepo.by_key(name_key) -> Supplier | None`; `QuotationRepo.for_version(version_id) -> Quotation | None`; `QuotationItemRepo.for_quotation(quotation_id)`, `reviewed_or_pinned(quotation_id)` (rows with `review_status != 'unreviewed'` **or** an id that appears in `match_suggestions.quotation_item_id` with status in `('confirmed','rejected')`), `delete_replaceable(quotation_id, keep_ids)`, `insert_many(rows)`.

`backend/app/modules/suppliers/schemas.py`:

```python
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class StoreResult:
    inserted: int
    duplicates_of_reviewed: int
    supplier_id: UUID
    quotation_id: UUID
    supplier_created: bool
```

`backend/app/modules/suppliers/service.py`:

```python
"""Supplier and quotation use cases (worker side in Slice 5a phase 1)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import OrgContext

from .models import Quotation, Supplier
from .repo import QuotationItemRepo, QuotationRepo, SupplierRepo
from .schemas import StoreResult

_SUFFIXES = re.compile(r"\b(pty|proprietary|ltd|limited|cc|inc|co|company|\(pty\))\b\.?", re.I)


def normalise_name(name: str) -> str:
    """Identity of a supplier name: lower case, company suffixes and punctuation removed."""
    text = _SUFFIXES.sub(" ", name.lower())
    text = re.sub(r"[^\w\s&]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _display(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    return name.title() if name.isupper() or name.islower() else name


def _jsonable(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in row.items()}


def _item_key(sku: object, description: object, unit: object) -> str:
    if sku:
        return "sku:" + str(sku).strip().lower()
    return "d:" + re.sub(r"\s+", " ", str(description or "")).strip().lower() + "|" + str(unit or "")


def _date(value: object) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def store_quotation(
    session: Session,
    ctx: OrgContext,
    version_id: UUID,
    run_id: UUID,
    header: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    fallback_name: str,
) -> StoreResult:
    suppliers_repo = SupplierRepo(session, ctx)
    quotations = QuotationRepo(session, ctx)
    items = QuotationItemRepo(session, ctx)
    flags = list(header.get("flags") or [])
    existing = quotations.for_version(version_id)

    created = False
    if existing is not None:
        supplier_id = existing.supplier_id  # a switch made by the user is never undone
    else:
        name = header.get("supplier_name") or fallback_name or "Unknown supplier"
        key = normalise_name(name) or "unknown supplier"
        supplier = suppliers_repo.by_key(key)
        if supplier is None:
            supplier = suppliers_repo.add(Supplier(name=_display(name)[:200], name_key=key[:200]))
            created = True
        supplier_id = supplier.id

    fields = {
        "reference": header.get("reference"),
        "quote_date": _date(header.get("quote_date")),
        "valid_until": _date(header.get("valid_until")),
        "currency": header.get("currency"),
        "prices_include_vat": header.get("prices_include_vat"),
    }
    if existing is None:
        quotation: Quotation = quotations.add(
            Quotation(document_version_id=version_id, run_id=run_id, supplier_id=supplier_id,
                      flags=flags, **fields)
        )
    else:
        quotation = existing
        quotation.run_id = run_id
        quotation.flags = flags
        for name_, value in fields.items():  # fill gaps only; never overwrite what is there
            if getattr(quotation, name_) is None and value is not None:
                setattr(quotation, name_, value)
        session.flush()

    kept = items.reviewed_or_pinned(quotation.id)
    seen = set()
    for item in kept:
        original = item.original_value or {}
        seen.add(_item_key(original.get("sku", item.sku), original.get("description", item.description),
                           original.get("unit", item.unit)))
    items.delete_replaceable(quotation.id, {i.id for i in kept})

    new_rows: list[dict[str, Any]] = []
    skipped = 0
    for cand in rows:
        key = _item_key(cand.get("sku"), cand.get("description"), cand.get("unit"))
        if key in seen:
            skipped += 1
            continue
        new_rows.append({
            "quotation_id": quotation.id, "document_version_id": version_id, "run_id": run_id,
            "position": len(new_rows), "source_order": int(cand.get("source_order", 0)),
            "description": cand["description"], "sku": cand.get("sku"), "unit": cand.get("unit"),
            "quantity": cand.get("quantity"), "unit_price": cand.get("unit_price"),
            "raw_unit": cand.get("raw_unit"), "raw_quantity": cand.get("raw_quantity"),
            "raw_price": cand.get("raw_price"), "flags": list(cand.get("flags") or []),
            "page_number": cand.get("page_number"), "sheet": cand.get("sheet"),
            "cell_range": cand.get("cell_range"), "original_value": _jsonable(cand),
        })  # fmt: skip
    items.insert_many(new_rows)
    return StoreResult(len(new_rows), skipped, supplier_id, quotation.id, created)
```

`backend/app/modules/suppliers/public.py`:

```python
"""Public surface of the suppliers module."""

from .schemas import StoreResult
from .service import normalise_name, store_quotation

__all__ = ["StoreResult", "normalise_name", "store_quotation"]
```

(`quotations.add` flushes, so `quotation.id` exists. `QuotationRepo`/`SupplierRepo` inherit `add` from `ScopedRepository`.)

- [ ] **Step 5: Run the store tests until green**

Run: `cd backend && DB_HOST_PORT=5433 uv run pytest tests/test_suppliers_store.py tests/test_suppliers_schema.py -q`
Expected: PASS.

- [ ] **Step 6: Write the failing pipeline test**

Create `backend/tests/test_quotation_pipeline.py` (uses `drain`, `register`, `make_tender`, `upload` from `tests.test_extraction_pipeline`/`tests.conftest`; fixtures from `backend/tests/fixtures/packs`):

```python
"""Quotations through the real worker."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.db.session import session_scope
from app.modules.suppliers.models import Quotation, QuotationItem, Supplier
from tests.conftest import make_tender, register, upload
from tests.test_extraction_pipeline import API, drain

PACKS = Path(__file__).parent / "fixtures" / "packs"


def _upload(actor, tender_id, pack: str, name: str):
    data = (PACKS / pack / name).read_bytes()
    body = upload(actor, tender_id, data, name, kind="quotation").json()
    drain()
    return body["version"]["id"]


def test_pdf_and_xlsx_quotations_are_extracted_end_to_end() -> None:
    actor = register("q@example.com")
    tender_id = make_tender(actor)
    pdf = _upload(actor, tender_id, "pack02", "quotation_1_sparkmore_supplies.pdf")
    xlsx = _upload(actor, tender_id, "pack02", "quotation_2_greenvale_cable_and_conduit.xlsx")
    with session_scope() as s:
        names = sorted(s.scalars(select(Supplier.name)))
        assert names == ["Greenvale Cable And Conduit", "Sparkmore Supplies"]
        counts = {str(q.document_version_id): len(s.scalars(select(QuotationItem).where(
            QuotationItem.quotation_id == q.id)).all()) for q in s.scalars(select(Quotation))}
        assert counts == {pdf: 15, xlsx: 15}
    status = actor.client.get(f"{API}/document-versions/{pdf}/extraction").json()
    quotation = next(k for k in status["kinds"] if k["kind"] == "quotation")
    assert quotation["job"]["status"] in ("succeeded", "succeeded_with_warnings")
    assert quotation["run"]["counts"]["items"] == 15


def test_two_quotes_from_one_supplier_share_the_supplier_row() -> None:
    actor = register("q2@example.com")
    tender_id = make_tender(actor)
    _upload(actor, tender_id, "pack02", "quotation_2_greenvale_cable_and_conduit.xlsx")
    _upload(actor, tender_id, "pack03", "quotation_1_greenvale_cable_and_conduit.pdf")
    with session_scope() as s:
        assert s.scalars(select(Supplier.name)).all() == ["Greenvale Cable And Conduit"]
        assert len(s.scalars(select(Quotation)).all()) == 2


def test_rerun_through_the_api_keeps_one_quotation_and_replaces_items() -> None:
    actor = register("q3@example.com")
    tender_id = make_tender(actor)
    version = _upload(actor, tender_id, "pack02", "quotation_2_greenvale_cable_and_conduit.xlsx")
    assert actor.client.post(f"{API}/document-versions/{version}/extract", json={"deep_scan": False}).status_code == 202
    drain()
    with session_scope() as s:
        assert len(s.scalars(select(Quotation)).all()) == 1
        assert len(s.scalars(select(QuotationItem)).all()) == 15


def test_a_quotation_without_a_table_completes_with_a_warning() -> None:
    from tests.conftest import make_pdf

    actor = register("q4@example.com")
    tender_id = make_tender(actor)
    body = upload(actor, tender_id, make_pdf(["Dear sir, we regret we cannot quote."]), "q.pdf", kind="quotation").json()
    drain()
    status = actor.client.get(f"{API}/document-versions/{body['version']['id']}/extraction").json()
    run = next(k for k in status["kinds"] if k["kind"] == "quotation")["run"]
    assert run["status"] == "succeeded_with_warnings"
    assert {"code": "NO_QUOTATION_FOUND"} in run["warnings"]
    with session_scope() as s:
        assert s.scalars(select(QuotationItem)).all() == []


def test_header_gaps_become_warnings() -> None:
    from tests.conftest import make_xlsx

    actor = register("q5@example.com")
    tender_id = make_tender(actor)
    rows = [["#", "Description", "Unit", "Qty", "Unit price"], ["1", "Cable", "m", "10", "5"]]
    body = upload(actor, tender_id, make_xlsx(rows, sheet="Quote"), "mystery quote.xlsx", kind="quotation").json()
    drain()
    run = next(k for k in actor.client.get(f"{API}/document-versions/{body['version']['id']}/extraction").json()["kinds"]
               if k["kind"] == "quotation")["run"]
    codes = {w["code"] for w in run["warnings"]}
    assert {"NO_SUPPLIER_NAME", "NO_CURRENCY", "NO_VALIDITY"} <= codes
    with session_scope() as s:
        assert s.scalars(select(Supplier.name)).all() == ["Mystery Quote"]


def test_other_documents_do_not_get_a_quotation_job() -> None:
    from tests.conftest import make_pdf

    actor = register("q6@example.com")
    tender_id = make_tender(actor)
    body = upload(actor, tender_id, make_pdf(["General conditions."]), "t.pdf").json()
    drain()
    kinds = {k["kind"]: k for k in actor.client.get(f"{API}/document-versions/{body['version']['id']}/extraction").json()["kinds"]}
    assert kinds["quotation"]["job"] is None
```

- [ ] **Step 7: Wire the job type, routing and handler**

`backend/app/modules/documents/service.py` near line 26-29:

```python
EXTRACT_QUOTATION_JOB = "extract_quotation"
EXTRACTION_JOBS = (EXTRACT_BOQ_JOB, EXTRACT_REQUIREMENTS_JOB, EXTRACT_QUOTATION_JOB)
```

and export `EXTRACT_QUOTATION_JOB` from `documents/public.py` (import and `__all__`, next to `EXTRACT_BOQ_JOB`).

`backend/app/modules/pipeline/routing.py`:

```python
    "quotation": (documents.EXTRACT_QUOTATION_JOB,),
...
KIND_OF_JOB = {
    documents.EXTRACT_BOQ_JOB: "boq",
    documents.EXTRACT_REQUIREMENTS_JOB: "requirements",
    documents.EXTRACT_QUOTATION_JOB: "quotation",
}
```

`backend/app/worker/handlers.py`: add `from pathlib import Path`, `from app.modules.suppliers import public as suppliers`, and

```python
def extract_quotation(
    session: Session, ctx: OrgContext, job: jobs.ClaimedJob, progress: ProgressFn
) -> list[dict[str, Any]]:
    _guard(session, ctx, job.subject_id)
    result = extraction.parse_quotation(_pages(session, ctx, job.subject_id))
    warnings: list[dict[str, Any]] = [{"code": flag} for flag in result.header.flags]
    warnings += result.warnings
    rows = _cap([c.as_row() for c in result.items], warnings)
    run = pipeline.run_for_job(session, ctx, job.id, "quotation")
    pipeline.lock_runs(session, ctx, job.subject_id, "quotation")
    filename = documents.get_version(session, ctx, job.subject_id).filename
    stored = suppliers.store_quotation(
        session, ctx, job.subject_id, run.id, result.header.as_row(), rows, Path(filename).stem
    )
    warnings += _replace_warning(stored.duplicates_of_reviewed)
    pipeline.finish_run(
        session, ctx, job.id, "quotation", warnings,
        {"items": stored.inserted, "supplier_created": stored.supplier_created},
    )  # fmt: skip
    progress(1, 1)
    return warnings
```

(Check `documents.get_version`'s name and signature in `documents/public.py` and use the existing call used elsewhere in `pipeline/service.py`.) Register in `HANDLERS`:

```python
    documents.EXTRACT_QUOTATION_JOB: JobHandler(
        run=extract_quotation, on_failure=_failer("quotation"), on_start=_starter("quotation")
    ),
```

`_starter("quotation")` already passes no prompt versions (only `requirements` does), which is correct.

- [ ] **Step 8: Run the whole backend suite**

Run: `cd backend && DB_HOST_PORT=5433 uv run pytest -q`
Expected: PASS. Fix regressions: existing tests that enumerate `KIND_OF_JOB`/the extraction status kinds (for example `test_extraction_api.py`) will now see a third kind `quotation`; update their expected lists, nothing else. Also the F1 sweep must still pass (no new routes in this phase).

- [ ] **Step 9: Lint and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
git add -A && git commit -m "feat: extract_quotation job, suppliers module and quotation storage"
```

---

### Task 4: Frontend status panel, docs and phase wrap-up

**Files:**
- Modify: `frontend/src/lib/status-text.ts` (+ test), `frontend/src/components/extraction-panel.tsx` (+ test)
- Modify: `docs/plan.md`, `docs/known-limitations.md`, `docs/superpowers/specs/2026-10-16-slice-5a-suppliers-matching-design.md`

**Interfaces:** consumes the `quotation` kind and its warning codes from Task 3; produces plain-words text only (no new API).

- [ ] **Step 1: Failing frontend tests**

In `frontend/src/lib/status-text.test.ts` add:

```ts
it("describes quotation extraction", () => {
  expect(kindLabel("quotation")).toBe("Quotation");
  expect(warningText({ code: "NO_SUPPLIER_NAME" })).toMatch(/supplier name/i);
  expect(warningText({ code: "NO_VALIDITY" })).toMatch(/valid/i);
  expect(warningText({ code: "NO_CURRENCY" })).toMatch(/currency/i);
  expect(warningText({ code: "VAT_UNKNOWN" })).toMatch(/VAT/);
  expect(warningText({ code: "QUOTE_NEEDS_MANUAL_ENTRY", pages: [1] })).toMatch(/scanned/i);
  expect(warningText({ code: "NO_QUOTATION_FOUND" })).toMatch(/no quotation/i);
});
```

In `frontend/src/components/extraction-panel.test.tsx` add a case that renders a status with a `quotation` kind whose run has `counts: { items: 15 }` and expects the text `15 items` and the label `Quotation`.

- [ ] **Step 2: Run, see them fail**

Run: `cd frontend && npx vitest run src/lib/status-text.test.ts src/components/extraction-panel.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `status-text.ts`: add `quotation: "Quotation"` to `EXTRACTION_LABELS`, and these cases to `warningText` (plain words; counts and page numbers only):

```ts
    case "NO_SUPPLIER_NAME":
      return "The supplier name could not be read, so the file name was used. Rename the supplier.";
    case "NO_REFERENCE":
      return "The quotation reference could not be read.";
    case "NO_QUOTE_DATE":
      return "The quotation date could not be read.";
    case "NO_VALIDITY":
      return "The quotation's validity date could not be read. Check it is still valid.";
    case "NO_CURRENCY":
      return "The currency could not be read. Check the prices before using them.";
    case "VAT_UNKNOWN":
      return "The quotation does not say whether prices include VAT.";
    case "QUOTE_NEEDS_MANUAL_ENTRY":
      return pagesSubject(pages, "looks like a scanned quotation.", "look like a scanned quotation.") + " Its items cannot be read automatically yet.";
    case "NO_QUOTATION_FOUND":
      return "No quotation table was found in this document.";
```

In `extraction-panel.tsx` `countText`: add

```ts
  if (kind === "quotation") {
    const items = n("items");
    return items === null ? null : `${items} ${items === 1 ? "item" : "items"}`;
  }
```

before the requirements fallthrough.

- [ ] **Step 4: Frontend checks**

Run: `cd frontend && npm run lint && npm run typecheck && npm test && npm run build; rm -rf .next`
Expected: all pass.

- [ ] **Step 5: Docs**

- `docs/superpowers/specs/2026-10-16-slice-5a-suppliers-matching-design.md` section 5 ("Persistence rules"): add that the worker handler for `extract_boq` passes the ids of BoQ items referenced by a `confirmed` or `rejected` match to `estimating.replace_unreviewed` as protected ids (they count as reviewed), mirroring the quotation-item rule; this wiring lands in Phase 2 together with matching, because decided matches cannot exist before then.
- `docs/known-limitations.md`: add a "Slice 5a" section: scanned quotations need manual entry (not yet possible); one quotation per document; a re-run fills only empty header fields and never undoes a supplier switch; prices in other currencies are shown but not converted.
- `docs/plan.md` Slice 5 row: append a status sentence for Phase 1 (what exists, test counts, and that parser accuracy on the five committed quotations is checked by `tests/test_quotation_parser.py`).

- [ ] **Step 6: Real-stack check (manual)**

Rebuild and restart the stack (`docker compose up -d --build api worker web`), upload the two pack02 quotations to a new tender in the browser, confirm each shows a "Quotation" extraction row with "15 items" and that the header warnings read sensibly. Record the result in the plan status line.

- [ ] **Step 7: Final suite and commit**

```bash
cd backend && DB_HOST_PORT=5433 uv run pytest -q && uv run ruff check . && uv run lint-imports
cd ../frontend && npm test
git add -A && git commit -m "feat: quotation status in the extraction panel; Slice 5a phase 1 docs"
```
