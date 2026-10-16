# Slice 4, Phase 1: Backend Review API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a signed-in estimator or admin confirm, correct or reject extracted BoQ lines and requirements through the API, with the Slice 3 parser fixes, a document-order sort key, reviewer names, a tender-wide requirements list, and the two read routes the review screen needs.

**Architecture:** Review writes are flat routes in a new `api/routers/review.py`. The router orchestrates: look the row up (404 if unknown or foreign), take the same `pipeline.lock_runs` lock extraction takes, then call the owning module's `review_item`, which re-reads the row and raises `409 row_replaced` if a re-run deleted it in between. `original_value` stays the immutable AI snapshot written at insert; a correction updates the main columns (the effective value) and records only the changed fields in `corrected_value`. A persisted `source_order` column gives lists a stable document-order sort across runs.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2, pytest (needs Postgres with pgvector), ruff, import-linter.

**Spec:** `docs/superpowers/specs/2026-10-16-slice-4-review-ui-design.md` (sections 1 to 3). This plan covers phase 1 only. Phases 2 to 6 (frontend) get their own plan after this one lands, because they depend on the real OpenAPI output.

## Global Constraints

- Branch `feat/slice-4-review-ui`. Run every command from `backend/` unless a step says otherwise.
- Tests need Postgres: from the repo root run `docker compose up -d db`; if it is not on 5432 set `DB_HOST_PORT` (see README). The suite drops and recreates `inteltps_test`.
- Review writes need `Permission.REVIEW_DATA`, held by **admin and estimator only**. Project managers and reviewers get 403. Do not change `ROLE_PERMISSIONS`.
- Error format is `{"error": {"code", "message", "details"?}}`. Unknown or other-organisation ids are **404** (F1 requires exactly 404). A row deleted between lookup and write is **409 `row_replaced`**.
- `original_value` is never rewritten. Quantity and rate are `Decimal` text on the wire (JSON strings matching `^-?\d{1,14}(\.\d{1,4})?$`), never JSON numbers; a blank quantity is `NULL`, never 0.
- Audit metadata uses only keys in `SAFE_METADATA_KEYS` (`status`, `fields`, ...): ids and field names, never document text.
- Modules import each other only through `public.py`; `app.kernel` and `app.modules.extraction` import neither `fastapi` nor `sqlalchemy`; raw `session.execute(` only in `repo.py` files.
- Every commit message ends with the attribution lines from the session's system reminder (`Co-Authored-By: ...` and `Claude-Session: ...`).
- After each task: `uv run ruff check . && uv run ruff format --check . && uv run lint-imports` must pass, plus the task's own tests.

## Review Focus

Inputs and conditions the spec implies but that are easy to get wrong; each has a pinning test in the task that owns the code.

1. A review request for a row a re-run already replaced: must be a clean 404 "replaced" for the UI, not a 500 (Task 6, Task 7).
2. A quantity sent as a JSON number, in exponent form, with more than four decimals, or with 15+ digits: must be 422, never rounded or stored (Task 6).
3. An empty patch, an unchanged value, a null description: 422 or a no-op, never a silent status change (Task 6).
4. A requirement whose evidence could not be located (no page): must sort last, not crash or sort first (Task 4).
5. A sheet window past the last row, or asked for on a PDF page: empty rows or the table untouched, never an error (Task 10).

---

### Task 1: Error code override, shared vocabulary, distinct 409 codes

**Files:**
- Modify: `app/kernel/errors.py:18-24`
- Create: `app/kernel/vocab.py`
- Modify: `app/modules/extraction/prompts.py:9-18`
- Modify: `app/modules/pipeline/service.py:667-677`
- Test: `tests/test_kernel_errors.py` (create), `tests/test_extraction_api.py` (append)

**Interfaces:**
- Produces: `DomainError(message, details, *, code=None)` (every subclass accepts `code=`); `app.kernel.vocab.REQUIREMENT_TYPES` and `MANDATORY_STATUSES` (tuples of str); extract 409 codes `not_processed`, `tender_archived`, `extraction_options_conflict`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kernel_errors.py`:

```python
"""Error code override and the shared requirement vocabulary."""

from __future__ import annotations

from app.kernel import Conflict, NotFound, vocab
from app.modules.extraction import prompts


def test_a_domain_error_can_override_its_code() -> None:
    assert Conflict("x").code == "conflict"
    err = Conflict("replaced", code="row_replaced")
    assert (err.code, err.message) == ("row_replaced", "replaced")
    assert NotFound().code == "not_found"


def test_the_prompt_schema_uses_the_shared_vocabulary() -> None:
    assert prompts.REQUIREMENT_TYPES == list(vocab.REQUIREMENT_TYPES)
    assert prompts.MANDATORY_STATUSES == list(vocab.MANDATORY_STATUSES)
```

Append to `tests/test_extraction_api.py`:

```python
def test_extract_conflicts_carry_distinct_codes() -> None:
    admin, tid, vid, _ = _ready()
    url = f"{API}/document-versions/{vid}/extract"
    r = admin.client.post(url, json={"deep_scan": False})  # ingest has not run: still pending
    assert (r.status_code, r.json()["error"]["code"]) == (409, "not_processed")
    drain()
    assert admin.client.post(url, json={"deep_scan": False}).status_code == 202
    r = admin.client.post(url, json={"deep_scan": True})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "extraction_options_conflict")
    drain()
    assert admin.client.post(f"{API}/tenders/{tid}/archive").status_code == 200
    r = admin.client.post(url, json={"deep_scan": False})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "tender_archived")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_kernel_errors.py tests/test_extraction_api.py::test_extract_conflicts_carry_distinct_codes -v`
Expected: FAIL (`vocab` import error; `TypeError` on `code=`).

- [ ] **Step 3: Implement**

Replace the `DomainError` class in `app/kernel/errors.py`:

```python
class DomainError(Exception):
    code = "error"

    def __init__(
        self, message: str = "", details: object | None = None, *, code: str | None = None
    ):
        if code is not None:
            self.code = code
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details
```

Create `app/kernel/vocab.py`:

```python
"""Closed vocabularies shared by extraction (the LLM schema) and checklist (review edits)."""

from __future__ import annotations

REQUIREMENT_TYPES: tuple[str, ...] = (
    "deadline",
    "meeting",
    "eligibility",
    "document",
    "pricing",
    "technical",
    "other",
)
MANDATORY_STATUSES: tuple[str, ...] = ("mandatory", "conditional", "informational")
```

In `app/modules/extraction/prompts.py` replace the two list literals (lines 9 to 18) with:

```python
from app.kernel import vocab

REQUIREMENT_TYPES = list(vocab.REQUIREMENT_TYPES)
MANDATORY_STATUSES = list(vocab.MANDATORY_STATUSES)
```

(place the import with the other imports at the top of the file, keeping ruff's import order).

In `app/modules/pipeline/service.py` change the three `Conflict(...)` raises in `request_extraction`:

```python
        raise Conflict("This tender is archived. Re-open it before extracting.", code="tender_archived")
```
```python
        raise Conflict("The document has not finished processing.", code="not_processed")
```
```python
                raise Conflict(
                    "An extraction with different options is already running.",
                    code="extraction_options_conflict",
                )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_kernel_errors.py tests/test_extraction_api.py tests/test_extraction_requirements.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/kernel app/modules/extraction/prompts.py app/modules/pipeline/service.py tests/test_kernel_errors.py tests/test_extraction_api.py
git commit -m "feat: error code override, shared requirement vocabulary, distinct extract 409 codes"
```

---

### Task 2: BoQ section carries across continuation pages

**Files:**
- Modify: `app/modules/extraction/boq.py:parse_boq` (the whole function)
- Test: `tests/test_boq_parser.py` (append)

**Interfaces:**
- Produces: `parse_boq` keeps the open section heading when a table continues the previous page's BoQ; a fresh header or a broken continuation resets it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_boq_parser.py`:

```python
def test_section_carries_across_a_continuation_page() -> None:
    p1 = _page(
        [HEADER, ["", "CABLES", "", "", "", ""], ["1.1", "Cable", "m", "5", "", ""]],
        kind="table", number=3, label=None,
    )  # fmt: skip
    p2 = _page([["1.2", "Conduit", "m", "7", "", ""]], kind="table", number=4, label=None)
    items = extraction.parse_boq([p1, p2]).items
    assert [(i.item_no, i.section) for i in items] == [("1.1", "CABLES"), ("1.2", "CABLES")]


def test_a_new_header_resets_the_section() -> None:
    p1 = _page(
        [HEADER, ["", "CABLES", "", "", "", ""], ["1.1", "Cable", "m", "5", "", ""]],
        kind="table", number=3, label=None,
    )  # fmt: skip
    p2 = _page([HEADER, ["2.1", "Lamp", "no", "3", "", ""]], kind="table", number=4, label=None)
    items = extraction.parse_boq([p1, p2]).items
    assert [(i.item_no, i.section) for i in items] == [("1.1", "CABLES"), ("2.1", None)]


def test_a_page_gap_drops_the_carried_section() -> None:
    p1 = _page(
        [HEADER, ["", "CABLES", "", "", "", ""], ["1.1", "Cable", "m", "5", "", ""]],
        kind="table", number=3, label=None,
    )  # fmt: skip
    p5 = _page([["1.2", "Conduit", "m", "7", "", ""]], kind="table", number=5, label=None)
    items = extraction.parse_boq([p1, p5]).items
    assert [i.item_no for i in items] == ["1.1"]  # page 5 is not a continuation (existing rule)
```

- [ ] **Step 2: Run to verify the first fails**

Run: `uv run pytest tests/test_boq_parser.py -k "section_carries or new_header_resets or page_gap" -v`
Expected: `test_section_carries_across_a_continuation_page` FAILS (`("1.2", None)`); the other two PASS already.

- [ ] **Step 3: Implement**

In `parse_boq` add `carried_section: str | None = None` next to `last_boq_page`; wherever `carried = None` is assigned (the page-gap check at the top of the page loop and the "not a continuation" branch) also assign `carried_section = None`; when a header is found set `carried_section = None` after `carried = (columns, width)`; and replace the line `section: str | None = None` with `section: str | None = carried_section`, then add `carried_section = section` after the row loop (same indentation as the `for offset, row` loop's parent block, i.e. at the end of the `for table in page.tables:` body). The resulting function body, in full:

```python
def parse_boq(pages: Sequence[PageInput]) -> BoqResult:
    result = BoqResult()
    carried: tuple[dict[str, int], int] | None = None  # header columns and width, across pages
    carried_section: str | None = None  # the open section heading, carried with the header
    last_boq_page: int | None = None  # page where the carried header was last seen or continued
    scanned: list[int] = []
    for page in pages:
        if carried is not None and (
            last_boq_page is None or page.page_number not in (last_boq_page, last_boq_page + 1)
        ):
            carried, carried_section = None, None  # a page gap ends the continuation
        if page.text_source == "ocr" and not page.tables:
            words = {w for w in re.findall(r"[a-z]+", page.text.lower())}
            hits = sum(
                1
                for field in SCAN_FIELDS
                if HEADER_WORDS[field] & words or (field == "quantity" and "qty" in words)
            )
            if hits >= 4:
                scanned.append(page.page_number)
            continue
        for table in page.tables:
            rows = [list(r) for r in table.get("rows", [])]
            if not rows:
                continue
            found = _find_header(rows)
            if found is not None:
                start, columns = found
                width = max(columns.values()) + 1
                width = max(width, max((len(rows[start]),), default=width))
                carried = (columns, width)
                carried_section = None
                last_boq_page = page.page_number
                body_from = start + 1
            elif carried is not None and table.get("kind") != "sheet":
                columns, width = carried
                if max(len(r) for r in rows) < width:
                    carried, carried_section = None, None  # not a continuation of the BoQ
                    continue
                last_boq_page = page.page_number
                body_from = 0
            else:
                continue
            section: str | None = carried_section
            for offset, row in enumerate(rows[body_from:], start=body_from):
                if not any(str(c or "").strip() for c in row):
                    continue
                description = _get(row, columns, "description")
                has_figures = any(
                    _get(row, columns, f) for f in ("unit", "quantity", "rate", "amount")
                )
                if not description or SUBTOTAL.match(description):
                    continue
                if TOTAL_WORD.match(description) and not (
                    _get(row, columns, "unit") or _get(row, columns, "quantity")
                ):
                    continue  # an amount-only total row, not an item
                if not has_figures:
                    section = description
                    continue
                result.items.append(_candidate(row, columns, section, page, table, offset, width))
                result.boq_pages.add(page.page_number)
            carried_section = section
    if scanned:
        result.warnings.append({"code": "BOQ_NEEDS_MANUAL_ENTRY", "pages": scanned})
    return result
```

- [ ] **Step 4: Run to verify all parser tests pass (including ground-truth scoring)**

Run: `uv run pytest tests/test_boq_parser.py -q`
Expected: PASS (the ground-truth scores must not regress).

- [ ] **Step 5: Commit**

```bash
git add app/modules/extraction/boq.py tests/test_boq_parser.py
git commit -m "fix: carry the BoQ section across continuation pages"
```

---

### Task 3: Ambiguous comma separator is flagged

**Files:**
- Modify: `app/modules/extraction/numbers.py` (append function)
- Modify: `app/modules/extraction/boq.py:_candidate`
- Modify: `app/modules/extraction/public.py`
- Test: `tests/test_boq_parser.py` (append)

**Interfaces:**
- Produces: `extraction.is_ambiguous_separator(value) -> bool` (True for `1,500`, `12,500`, `R 1,500`; False for `1,250,500`, `1,25`, `1.500,00`). `_candidate` adds the flag `ambiguous_separator` to a BoQ line when its raw quantity or rate text is ambiguous. The parsed value is unchanged (still read as thousands) so nothing is lost.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_boq_parser.py`:

```python
@pytest.mark.parametrize(
    ("raw", "ambiguous"),
    [
        ("1,500", True),
        ("12,500", True),
        ("R 1,500", True),
        ("1 500", False),
        ("1,250,500", False),
        ("1,25", False),
        ("1.500,00", False),
        ("1500", False),
        ("", False),
        (None, False),
    ],
)
def test_is_ambiguous_separator(raw, ambiguous) -> None:
    assert extraction.is_ambiguous_separator(raw) is ambiguous


def test_ambiguous_quantity_and_rate_are_flagged_but_still_parsed() -> None:
    rows = [HEADER, ["1.1", "Cable", "m", "1,500", "2,500", ""], ["1.2", "Lamp", "no", "3", "", ""]]
    items = {i.item_no: i for i in extraction.parse_boq([_page(rows)]).items}
    assert items["1.1"].quantity == Decimal("1500") and items["1.1"].rate == Decimal("2500")
    assert "ambiguous_separator" in items["1.1"].flags
    assert "ambiguous_separator" not in items["1.2"].flags
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_boq_parser.py -k "ambiguous" -v`
Expected: FAIL (`AttributeError: is_ambiguous_separator`).

- [ ] **Step 3: Implement**

Append to `app/modules/extraction/numbers.py`:

```python
_SINGLE_COMMA_THREE = re.compile(r"\d{1,3},\d{3}")


def is_ambiguous_separator(value: object) -> bool:
    """True for a lone comma followed by exactly three digits (`1,500`). South African usage
    can mean 1.5 or 1500; `parse_decimal` reads it as 1500 and the line is flagged for review."""
    text = _SPACES.sub("", str(value if value is not None else ""))
    text = re.sub(r"^[Rr](?=[\d.,])", "", text)
    return _SINGLE_COMMA_THREE.fullmatch(text) is not None
```

In `app/modules/extraction/boq.py` change the import to `from .numbers import is_ambiguous_separator, parse_decimal` and, in `_candidate`, add after the `raw_rate`/`rate` lines (before `sheet = cell_range = page_number = None`):

```python
    if is_ambiguous_separator(raw_quantity) or is_ambiguous_separator(raw_rate):
        flags.append("ambiguous_separator")
```

In `app/modules/extraction/public.py` change `from .numbers import parse_decimal` to `from .numbers import is_ambiguous_separator, parse_decimal` and add `"is_ambiguous_separator",` to `__all__` (alphabetical position, after `"extract_requirements"`).

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_boq_parser.py -q`
Expected: PASS (ground-truth scores unchanged: the flag does not alter values).

- [ ] **Step 5: Commit**

```bash
git add app/modules/extraction tests/test_boq_parser.py
git commit -m "feat: flag ambiguous comma separators in BoQ quantities and rates"
```

---

### Task 4: `source_order` column, migration and list ordering

**Files:**
- Modify: `app/modules/extraction/types.py` (add helper + field + `as_row`)
- Modify: `app/modules/extraction/boq.py` (`_candidate` signature and call)
- Modify: `app/modules/extraction/public.py`
- Modify: `app/modules/estimating/models.py`, `app/modules/checklist/models.py`
- Create: `migrations/versions/0004_source_order.py`
- Modify: `app/modules/estimating/service.py`, `app/modules/estimating/repo.py`
- Modify: `app/modules/checklist/service.py`, `app/modules/checklist/repo.py`
- Test: `tests/test_source_order.py` (create)

**Interfaces:**
- Produces: `extraction.source_order(page_number: int | None, position: int | None) -> int`; `BoqCandidate.source_order: int = 0`; both `as_row()` dicts carry `"source_order"`; `boq_items.source_order` and `requirements.source_order` (`INTEGER NOT NULL DEFAULT 0`); lists order by `(source_order, position, id)`.
- A located item sorts by `page * 1_000_000 + position-in-page`; an unlocated one (`page_number is None`) sorts last (`2_000_000_000`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_source_order.py`:

```python
"""Document-order sort key: pure helper, parser output, and list order across a re-run."""

from __future__ import annotations

from sqlalchemy import update

from app.db.session import session_scope
from app.modules.estimating.models import BoqItem
from app.modules.extraction import public as extraction
from tests.review_helpers import BOQ_ROWS, boq_items, boq_version
from tests.test_extraction_pipeline import API, drain


def test_source_order_sorts_by_page_then_position_and_unlocated_last() -> None:
    assert extraction.source_order(1, 5) < extraction.source_order(1, 6)
    assert extraction.source_order(1, 999_999) < extraction.source_order(2, 0)
    assert extraction.source_order(3, None) == extraction.source_order(3, 0)
    assert extraction.source_order(None, 40) > extraction.source_order(5000, 999_999)


def test_requirement_rows_without_a_page_sort_last() -> None:
    located = extraction.RequirementCandidate("d", "other", "mandatory", "q", 2, 10, 20).as_row()
    unlocated = extraction.RequirementCandidate("d", "other", "mandatory", "q").as_row()
    assert located["source_order"] < unlocated["source_order"]


def test_parser_assigns_increasing_source_order() -> None:
    from tests.test_boq_parser import HEADER, _page

    rows = [HEADER, ["1.1", "A", "m", "1", "", ""], ["1.2", "B", "m", "2", "", ""]]
    items = extraction.parse_boq([_page(rows)]).items
    assert items[0].source_order < items[1].source_order


def test_lists_keep_document_order_when_a_reviewed_row_survives_a_rerun() -> None:
    admin, _, vid = boq_version()
    ordered = [i["item_no"] for i in boq_items(admin, vid)]
    assert ordered == [r[0] for r in BOQ_ROWS[1:]]
    middle = boq_items(admin, vid)[1]["id"]
    with session_scope() as s:  # simulate a reviewer having confirmed the middle line
        s.execute(update(BoqItem).where(BoqItem.id == middle).values(review_status="confirmed"))
    admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    drain()
    after = boq_items(admin, vid)
    assert [i["item_no"] for i in after] == ordered  # not: the old reviewed row first
    assert after[1]["id"] == middle and len(after) == 3
```

Create `tests/review_helpers.py` (shared by later tasks):

```python
"""Builders shared by the review tests."""

from __future__ import annotations

from tests.conftest import Actor, make_tender, make_xlsx, register, upload
from tests.test_extraction_pipeline import API, CLAUSE, drain, req_json, tender_pdf

BOQ_ROWS = [
    ["Item", "Description", "Unit", "Quantity", "Rate", "Amount"],
    ["1.1", "Cable 4mm", "Metre", "10", "5", ""],
    ["1.2", "Board 63 A", "each", "2", "", ""],
    ["1.3", "Conduit 20mm", "Metre", "", "", ""],
]


def boq_version(actor: Actor | None = None, rows: list[list[object]] | None = None):
    """An organisation with an extracted XLSX BoQ. Returns (actor, tender_id, version_id)."""
    actor = actor or register("est@example.com")
    tender_id = make_tender(actor)
    body = upload(actor, tender_id, make_xlsx(rows or BOQ_ROWS), "boq.xlsx", kind="boq").json()
    drain()
    return actor, tender_id, body["version"]["id"]


def boq_items(actor: Actor, version_id: str) -> list[dict]:
    return actor.client.get(f"{API}/document-versions/{version_id}/boq-items").json()


def requirement_version(fake_llm, actor: Actor | None = None):
    """An organisation with one extracted requirement. Returns (actor, tender_id, version_id)."""
    fake_llm([req_json(CLAUSE)])
    actor = actor or register("est@example.com")
    tender_id = make_tender(actor)
    body = upload(actor, tender_id, tender_pdf(), "t.pdf").json()
    drain()
    return actor, tender_id, body["version"]["id"]


def requirements(actor: Actor, version_id: str) -> list[dict]:
    return actor.client.get(f"{API}/document-versions/{version_id}/requirements").json()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_source_order.py -v`
Expected: FAIL (`AttributeError: source_order`; `column source_order does not exist`).

- [ ] **Step 3: Implement**

`app/modules/extraction/types.py`: add near the top (after `PageInput`):

```python
SOURCE_STRIDE = 1_000_000
SOURCE_UNLOCATED = 2_000_000_000  # below int32 max; sorts after every located item


def source_order(page_number: int | None, position: int | None) -> int:
    """Document-order sort key: page (or sheet) first, then the position inside it. Items whose
    page is unknown (unverified evidence) sort last."""
    if page_number is None:
        return SOURCE_UNLOCATED
    inside = max(0, min(position or 0, SOURCE_STRIDE - 1))
    return min(page_number, 1999) * SOURCE_STRIDE + inside
```

In `BoqCandidate` add the last field `source_order: int = 0` and `"source_order": self.source_order,` in `as_row` (after `"cell_range"`). In `RequirementCandidate.as_row` add `"source_order": source_order(self.page_number, self.quote_start),`.

`app/modules/extraction/boq.py`: import `source_order` (`from .types import BOQ_TEXT_LIMITS, BoqCandidate, BoqResult, PageInput, source_order`); give `_candidate` a trailing parameter `order: int` and set `source_order=order` in the `BoqCandidate(...)` call; in `parse_boq` call `_candidate(row, columns, section, page, table, offset, width, source_order(page.page_number, offset))`.

`app/modules/extraction/public.py`: `from .types import (..., source_order)` and add `"source_order"` to `__all__`.

Models (`estimating/models.py`, `checklist/models.py`): add the column after `position`:

```python
    source_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
```
and change the index to `Index("ix_boq_items_version", "document_version_id", "source_order", "position")` (and `ix_requirements_version` likewise).

Create `migrations/versions/0004_source_order.py`:

```python
"""source_order

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16 09:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

TABLES = (("boq_items", "ix_boq_items_version"), ("requirements", "ix_requirements_version"))


def upgrade() -> None:
    for table, index in TABLES:
        op.add_column(table, sa.Column('source_order', sa.Integer(), server_default='0', nullable=False))
        op.drop_index(index, table_name=table)
        op.create_index(index, table, ['document_version_id', 'source_order', 'position'], unique=False)


def downgrade() -> None:
    for table, index in TABLES:
        op.drop_index(index, table_name=table)
        op.create_index(index, table, ['document_version_id', 'position'], unique=False)
        op.drop_column(table, 'source_order')
```

Services: in `estimating/service.py` `replace_unreviewed` row dict add `"source_order": int(cand.get("source_order", 0)),` after `"position"`; same in `checklist/service.py`.

Repos: `estimating/repo.py` `for_version` → `.order_by(BoqItem.source_order, BoqItem.position, BoqItem.id)`; `checklist/repo.py` → `.order_by(Requirement.source_order, Requirement.position, Requirement.id)`.

- [ ] **Step 4: Run to verify they pass, and that migrations match the models**

Run: `uv run pytest tests/test_source_order.py tests/test_fitness_functions.py tests/test_extraction_store.py tests/test_extraction_pipeline.py tests/test_boq_parser.py -q`
Expected: PASS (`test_fitness_functions` includes the migrations-match-models check).

- [ ] **Step 5: Commit**

```bash
git add app tests migrations
git commit -m "feat: persisted source_order so lists keep document order across re-runs"
```

---

### Task 5: DTO review fields and reviewer names

**Files:**
- Modify: `app/modules/estimating/schemas.py`, `app/modules/estimating/service.py` (`_dto`)
- Modify: `app/modules/checklist/schemas.py`, `app/modules/checklist/service.py` (`_dto`)
- Modify: `app/modules/identity/repo.py` (`MembershipRepo.names_for`), `app/modules/identity/service.py`, `app/modules/identity/public.py`
- Create: `app/api/reviewers.py`
- Modify: `app/api/routers/extraction.py` (the two list routes)
- Modify: `tests/test_repository_contract.py`
- Test: `tests/test_review_dto.py` (create)

**Interfaces:**
- Produces: both item DTOs gain `original_value: dict[str, Any]`, `reviewed_by: UUID | None`, `reviewed_by_name: str | None = None`, `reviewed_at: datetime | None`. `identity.member_names(session, ctx, user_ids) -> dict[UUID, str]` (needs `READ`, same organisation only). `app.api.reviewers.with_reviewer_names(session, ctx, dtos) -> list` fills `reviewed_by_name` in place and returns the list.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_review_dto.py`:

```python
"""The list DTOs expose the review fields."""

from __future__ import annotations

from decimal import Decimal

from tests.review_helpers import boq_items, boq_version, requirement_version, requirements


def test_boq_items_expose_the_original_snapshot_and_empty_review_fields() -> None:
    admin, _, vid = boq_version()
    first = boq_items(admin, vid)[0]
    assert first["item_no"] == "1.1"
    assert Decimal(first["original_value"]["quantity"]) == 10
    assert first["original_value"]["description"] == "Cable 4mm"
    assert first["reviewed_by"] is None and first["reviewed_by_name"] is None
    assert first["reviewed_at"] is None and first["review_status"] == "unreviewed"


def test_requirements_expose_the_original_snapshot(fake_llm) -> None:
    admin, _, vid = requirement_version(fake_llm)
    row = requirements(admin, vid)[0]
    assert row["original_value"]["requirement_type"] == "document"
    assert row["reviewed_by"] is None and row["reviewed_at"] is None
```

In `tests/test_repository_contract.py` add, inside `test_repositories_never_return_another_organisations_rows` just after the `count_active_admins` assertion:

```python
        user_b = s.scalar(select(Membership.user_id).where(Membership.organisation_id == org_b))
        assert repos["MembershipRepo"].names_for({user_b}) == {}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_review_dto.py tests/test_repository_contract.py -v`
Expected: FAIL (`KeyError: 'original_value'`; `names_for` missing).

- [ ] **Step 3: Implement**

`estimating/schemas.py`: add `from datetime import datetime` and append to `BoqItemDTO`:

```python
    original_value: dict[str, Any] = {}
    reviewed_by: UUID | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
```
Same four fields appended to `RequirementDTO` in `checklist/schemas.py` (import `datetime` there too).

In each `_dto(...)` add `original_value=dict(item.original_value or {}), reviewed_by=item.reviewed_by, reviewed_at=item.reviewed_at,` (use `item` in checklist, `item` in estimating: both name the parameter `item`).

`identity/repo.py`, inside `MembershipRepo` (make sure `select` and `Collection` are imported: `from collections.abc import Collection`, and `from sqlalchemy import select` if not already):

```python
    def names_for(self, user_ids: Collection[UUID]) -> dict[UUID, str]:
        """Display names of this organisation's members, for showing who reviewed a row."""
        if not user_ids:
            return {}
        rows = self.session.execute(
            select(Membership.user_id, User.name)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organisation_id == self.ctx.organisation_id,
                Membership.user_id.in_(user_ids),
            )
        ).all()
        return {user_id: name for user_id, name in rows}
```

`identity/service.py` add:

```python
def member_names(session: Session, ctx: OrgContext, user_ids: Collection[UUID]) -> dict[UUID, str]:
    ctx.require(Permission.READ)
    return MembershipRepo(session, ctx).names_for(set(user_ids))
```
(import `Collection` from `collections.abc`), and export `member_names` from `identity/public.py` (`import` line and `__all__`).

Create `app/api/reviewers.py`:

```python
"""Fill `reviewed_by_name` on review DTOs (estimators cannot list members, but may see names)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import OrgContext
from app.modules.identity import public as identity


class _Reviewed(Protocol):
    reviewed_by: UUID | None
    reviewed_by_name: str | None


def with_reviewer_names[T: _Reviewed](session: Session, ctx: OrgContext, dtos: Sequence[T]) -> list[T]:
    ids = {d.reviewed_by for d in dtos if d.reviewed_by}
    names = identity.member_names(session, ctx, ids) if ids else {}
    for dto in dtos:
        if dto.reviewed_by:
            dto.reviewed_by_name = names.get(dto.reviewed_by)
    return list(dtos)
```

`routers/extraction.py`: `from app.api.reviewers import with_reviewer_names`; wrap both returns: `return with_reviewer_names(session, ctx, estimating.list_boq_items(session, ctx, version_id, limit, offset))` and the same for `checklist.list_requirements`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_review_dto.py tests/test_repository_contract.py tests/test_extraction_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat: expose review fields and reviewer names on BoQ and requirement DTOs"
```

---

### Task 6: Review BoQ lines (patch, confirm, reject)

**Files:**
- Modify: `app/modules/estimating/schemas.py` (add `BoqPatch`), `app/modules/estimating/repo.py` (`version_id_of`, `fresh`), `app/modules/estimating/service.py` (`version_of`, `review_item`), `app/modules/estimating/public.py`
- Create: `app/api/routers/review.py`
- Modify: `app/api/main.py` (include the router)
- Modify: `tests/test_repository_contract.py`
- Test: `tests/test_review_boq.py` (create)

**Interfaces:**
- Consumes: `with_reviewer_names` (Task 5), `Conflict(code=)` (Task 1), `pipeline.lock_runs(session, ctx, version_id, kind)`.
- Produces: `estimating.BoqPatch`; `estimating.version_of(session, ctx, item_id) -> UUID` (404 if unknown/foreign; 403 without `REVIEW_DATA`); `estimating.review_item(session, ctx, item_id, action: Literal["confirm","reject","correct"], patch: BoqPatch | None = None) -> BoqItemDTO` (409 `row_replaced` if the row is gone); routes `PATCH /api/v1/boq-items/{boq_item_id}`, `POST .../confirm`, `POST .../reject`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_review_boq.py`:

```python
"""BoQ review: correct, confirm, reject; validation; roles; re-runs; audit."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.session import session_scope
from app.kernel import Conflict, OrgContext, Role
from app.modules.audit.models import AuditEvent
from app.modules.estimating import public as estimating
from tests.conftest import add_member
from tests.review_helpers import boq_items, boq_version
from tests.test_extraction_pipeline import API, drain


def _item(actor, vid, number):
    return next(i for i in boq_items(actor, vid) if i["item_no"] == number)


def _patch(actor, item_id, body):
    return actor.client.patch(f"{API}/boq-items/{item_id}", json=body)


def test_correcting_a_quantity_updates_the_value_and_keeps_the_original() -> None:
    admin, _, vid = boq_version()
    item = _item(admin, vid, "1.1")
    r = _patch(admin, item["id"], {"quantity": "12.5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["quantity"]) == Decimal("12.5") and body["review_status"] == "corrected"
    assert body["corrected_value"] == {"quantity": "12.5"}
    assert Decimal(body["original_value"]["quantity"]) == 10
    assert body["reviewed_by"] == admin.me["user_id"] and body["reviewed_at"]
    assert body["reviewed_by_name"] == admin.me["name"]

    again = _patch(admin, item["id"], {"description": "Cable 6mm"}).json()
    assert again["corrected_value"] == {"quantity": "12.5", "description": "Cable 6mm"}
    assert again["original_value"] == body["original_value"]  # immutable snapshot


def test_confirm_reject_and_changing_your_mind() -> None:
    admin, _, vid = boq_version()
    item_id = _item(admin, vid, "1.2")["id"]
    ok = admin.client.post(f"{API}/boq-items/{item_id}/confirm").json()
    assert ok["review_status"] == "confirmed" and ok["corrected_value"] is None
    assert admin.client.post(f"{API}/boq-items/{item_id}/reject").json()["review_status"] == "rejected"
    assert admin.client.post(f"{API}/boq-items/{item_id}/confirm").json()["review_status"] == "confirmed"
    fixed = _patch(admin, item_id, {"unit": "no"}).json()
    assert fixed["review_status"] == "corrected" and fixed["unit"] == "no"


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": 12.5},  # a JSON number, not text
        {"quantity": "1e3"},
        {"quantity": "1.23456"},  # more than four decimals
        {"quantity": "1" * 15},  # overflows NUMERIC(18,4)
        {"quantity": "abc"},
        {"rate": "-"},
        {},  # nothing to change
        {"description": None},  # cannot be cleared
        {"description": "   "},
        {"bogus": 1},  # unknown field
    ],
)
def test_invalid_patches_are_rejected(body) -> None:
    admin, _, vid = boq_version()
    item = _item(admin, vid, "1.1")
    r = _patch(admin, item["id"], body)
    assert r.status_code == 422, r.text
    assert _item(admin, vid, "1.1")["review_status"] == "unreviewed"  # nothing was written


def test_an_unchanged_value_is_a_no_op() -> None:
    admin, _, vid = boq_version()
    item = _item(admin, vid, "1.1")
    r = _patch(admin, item["id"], {"quantity": "10", "description": item["description"]})
    assert r.status_code == 200 and r.json()["review_status"] == "unreviewed"
    assert r.json()["reviewed_by"] is None


def test_adding_a_quantity_clears_the_missing_flag_and_clearing_it_restores_it() -> None:
    admin, _, vid = boq_version()
    item = _item(admin, vid, "1.3")
    assert "missing_quantity" in item["flags"] and item["quantity"] is None
    filled = _patch(admin, item["id"], {"quantity": "4"}).json()
    assert "missing_quantity" not in filled["flags"] and Decimal(filled["quantity"]) == 4
    cleared = _patch(admin, item["id"], {"quantity": None}).json()
    assert cleared["quantity"] is None and "missing_quantity" in cleared["flags"]


def test_only_admin_and_estimator_may_review() -> None:
    admin, _, vid = boq_version()
    item_id = _item(admin, vid, "1.1")["id"]
    for role in ("reviewer", "project_manager"):
        other = add_member(admin, f"{role}@example.com", role)
        assert _patch(other, item_id, {"unit": "m"}).status_code == 403
        assert other.client.post(f"{API}/boq-items/{item_id}/confirm").status_code == 403
        assert other.client.post(f"{API}/boq-items/{item_id}/reject").status_code == 403
        assert other.client.get(f"{API}/document-versions/{vid}/boq-items").status_code == 200
    estimator = add_member(admin, "estimator@example.com", "estimator", name="Esta Mator")
    assert estimator.client.post(f"{API}/boq-items/{item_id}/confirm").status_code == 200
    reader = add_member(admin, "reader@example.com", "reviewer")
    seen = _item(reader, vid, "1.1")
    assert seen["reviewed_by_name"] == "Esta Mator"  # a reader can see who reviewed


def test_an_id_replaced_by_a_rerun_is_a_404_and_reviewed_rows_survive() -> None:
    admin, _, vid = boq_version()
    kept = _item(admin, vid, "1.2")["id"]
    stale = _item(admin, vid, "1.1")["id"]
    admin.client.post(f"{API}/boq-items/{kept}/confirm")
    admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    drain()
    after = boq_items(admin, vid)
    assert len(after) == 3 and any(i["id"] == kept for i in after)
    assert _patch(admin, stale, {"unit": "m"}).status_code == 404
    assert admin.client.post(f"{API}/boq-items/{uuid4()}/confirm").status_code == 404


def test_a_row_deleted_before_the_write_is_row_replaced() -> None:
    admin, _, _ = boq_version()
    ctx = OrgContext(UUID(admin.me["user_id"]), UUID(admin.org_id), Role.ADMIN)
    with session_scope() as s, pytest.raises(Conflict) as exc:
        estimating.review_item(s, ctx, uuid4(), "confirm")
    assert exc.value.code == "row_replaced"


def test_review_writes_take_the_extraction_lock(monkeypatch) -> None:
    from app.api.routers import review

    admin, _, vid = boq_version()
    item_id = _item(admin, vid, "1.1")["id"]
    calls = []
    real = review.pipeline.lock_runs

    def spy(session, ctx, version_id, kind):
        calls.append((str(version_id), kind))
        return real(session, ctx, version_id, kind)

    monkeypatch.setattr(review.pipeline, "lock_runs", spy)
    admin.client.post(f"{API}/boq-items/{item_id}/confirm")
    assert calls == [(vid, "boq")]


def test_review_is_audited_with_field_names_only() -> None:
    admin, _, vid = boq_version()
    item_id = _item(admin, vid, "1.1")["id"]
    _patch(admin, item_id, {"description": "Secret cable text"})
    with session_scope() as s:
        event = s.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "boq_item")
        ).one()
    assert event.action == "review_corrected"
    assert event.event_metadata == {"status": "corrected", "fields": ["description"]}
    assert "Secret" not in str(event.event_metadata)
```

In `tests/test_repository_contract.py`, after the `repos["BoqRepo"].for_version(...)` line add:

```python
        with pytest.raises(NotFound):
            repos["BoqRepo"].version_id_of(b_ids["BoqRepo"][0])
        assert repos["BoqRepo"].fresh(b_ids["BoqRepo"][0]) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_review_boq.py -q`
Expected: FAIL (404/405 on the new routes; import errors).

- [ ] **Step 3: Implement**

`estimating/schemas.py` add (imports: `Annotated`, `ConfigDict`, `StringConstraints`, `model_validator` from pydantic):

```python
DecimalText = Annotated[str, StringConstraints(pattern=r"^-?\d{1,14}(\.\d{1,4})?$")]


class BoqPatch(BaseModel):
    """The fields a reviewer may change. Absent means unchanged; null clears a nullable field.
    Decimals are JSON strings, never numbers."""

    model_config = ConfigDict(extra="forbid")

    section: Annotated[str, StringConstraints(max_length=300)] | None = None
    item_no: Annotated[str, StringConstraints(max_length=50)] | None = None
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = None
    unit: Annotated[str, StringConstraints(max_length=30)] | None = None
    quantity: DecimalText | None = None
    rate: DecimalText | None = None

    @model_validator(mode="after")
    def _check(self) -> BoqPatch:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        if "description" in self.model_fields_set and self.description is None:
            raise ValueError("The description cannot be cleared.")
        return self
```

`estimating/repo.py` (add `from sqlalchemy import insert, select` and `from app.kernel import NotFound`):

```python
    def version_id_of(self, item_id: UUID) -> UUID:
        version_id = self.session.scalar(
            select(BoqItem.document_version_id).where(
                BoqItem.organisation_id == self.ctx.organisation_id, BoqItem.id == item_id
            )
        )
        if version_id is None:
            raise NotFound("BoqItem not found")
        return version_id

    def fresh(self, item_id: UUID) -> BoqItem | None:
        """Re-read the row after taking the extraction lock; None when a re-run deleted it."""
        return self.session.scalar(
            self._select().where(BoqItem.id == item_id).execution_options(populate_existing=True)
        )
```

`estimating/service.py` add imports (`from datetime import UTC, datetime`, `from typing import Literal`, `from app.kernel import Conflict, OrgContext, Permission, ValidationFailed`, `from app.modules.audit import public as audit`, `from .schemas import BoqItemDTO, BoqPatch, ReplaceResult`) and:

```python
def version_of(session: Session, ctx: OrgContext, item_id: UUID) -> UUID:
    """The version a line belongs to, so the caller can take the extraction lock first."""
    ctx.require(Permission.REVIEW_DATA)
    return BoqRepo(session, ctx).version_id_of(item_id)


def _apply(row: BoqItem, patch: BoqPatch) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for name in patch.model_fields_set:
        new: Any = getattr(patch, name)
        if name in ("quantity", "rate") and new is not None:
            new = Decimal(new)
        if new == getattr(row, name):
            continue
        setattr(row, name, new)
        changes[name] = str(new) if isinstance(new, Decimal) else new
    flags = list(row.flags)
    if "quantity" in changes:
        if row.quantity is None:
            if "missing_quantity" not in flags:
                flags.append("missing_quantity")
        else:
            flags = [f for f in flags if f not in ("missing_quantity", "quantity_unparsed")]
    if "rate" in changes and row.rate is not None:
        flags = [f for f in flags if f != "rate_unparsed"]
    row.flags = flags  # a new list, so the JSONB change is detected
    return changes


def review_item(
    session: Session,
    ctx: OrgContext,
    item_id: UUID,
    action: Literal["confirm", "reject", "correct"],
    patch: BoqPatch | None = None,
) -> BoqItemDTO:
    """Call with the extraction lock held (`pipeline.lock_runs`). A line a re-run deleted since
    the caller looked it up is `row_replaced`."""
    ctx.require(Permission.REVIEW_DATA)
    row = BoqRepo(session, ctx).fresh(item_id)
    if row is None:
        raise Conflict(
            "This line was replaced by a newer extraction. Reload the list.", code="row_replaced"
        )
    fields: list[str] = []
    if action == "correct":
        if patch is None:
            raise ValidationFailed("No changes were given.")
        changes = _apply(row, patch)
        if not changes:
            return _dto(row)
        row.corrected_value = {**(row.corrected_value or {}), **changes}
        row.review_status = "corrected"
        fields = sorted(changes)
    else:
        row.review_status = "confirmed" if action == "confirm" else "rejected"
    row.reviewed_by, row.reviewed_at = ctx.user_id, datetime.now(UTC)
    audit.record(
        session, ctx, "boq_item", row.id, f"review_{row.review_status}",
        {"status": row.review_status, "fields": fields},
    )  # fmt: skip
    session.flush()
    return _dto(row)
```

`estimating/public.py`: export `BoqPatch`, `review_item`, `version_of`.

Create `app/api/routers/review.py`:

```python
"""Review writes: confirm, correct or reject extracted rows (Slice 4).

Each write looks the row up (404 if unknown or foreign), takes the same lock extraction takes
for that version and kind, then lets the owning module re-read and write (409 `row_replaced`
if a re-run deleted the row in between)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.api.reviewers import with_reviewer_names
from app.modules.estimating import public as estimating
from app.modules.pipeline import public as pipeline

router = APIRouter(prefix="/api/v1", tags=["review"])


def _boq(session, ctx, item_id: UUID, action, patch=None):
    version_id = estimating.version_of(session, ctx, item_id)
    pipeline.lock_runs(session, ctx, version_id, "boq")
    dto = estimating.review_item(session, ctx, item_id, action, patch)
    return with_reviewer_names(session, ctx, [dto])[0]


@router.patch("/boq-items/{boq_item_id}", response_model=estimating.BoqItemDTO)
def correct_boq_item(boq_item_id: UUID, body: estimating.BoqPatch, ctx: Ctx, session: DbSession):
    return _boq(session, ctx, boq_item_id, "correct", body)


@router.post("/boq-items/{boq_item_id}/confirm", response_model=estimating.BoqItemDTO)
def confirm_boq_item(boq_item_id: UUID, ctx: Ctx, session: DbSession):
    return _boq(session, ctx, boq_item_id, "confirm")


@router.post("/boq-items/{boq_item_id}/reject", response_model=estimating.BoqItemDTO)
def reject_boq_item(boq_item_id: UUID, ctx: Ctx, session: DbSession):
    return _boq(session, ctx, boq_item_id, "reject")
```

`app/api/main.py`: add `review` to the `from app.api.routers import ...` list and `app.include_router(review.router)` after the extraction router.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_review_boq.py tests/test_repository_contract.py -q`
Expected: PASS. (`tests/test_fitness_functions.py` F1 will now fail on the unknown `boq_item_id`; Task 8 fixes it. Do not run the full suite until then.)

- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat: review BoQ lines (correct, confirm, reject) with the extraction lock"
```

---

### Task 7: Review requirements

**Files:**
- Modify: `app/modules/checklist/schemas.py` (add `RequirementPatch`), `repo.py` (`version_id_of`, `fresh`), `service.py` (`version_of`, `review_item`), `public.py`
- Modify: `app/api/routers/review.py`
- Modify: `tests/test_repository_contract.py`
- Test: `tests/test_review_requirements.py` (create)

**Interfaces:**
- Produces: `checklist.RequirementPatch` (`description`, `requirement_type`, `mandatory_status`; types validated against `kernel.vocab`); `checklist.version_of`, `checklist.review_item` with the same contract as the BoQ ones; routes `PATCH /api/v1/requirements/{requirement_id}`, `POST .../confirm`, `POST .../reject` (run kind `"requirements"`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_review_requirements.py`:

```python
"""Requirement review: same rules as BoQ review, different fields."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.conftest import add_member
from tests.review_helpers import requirement_version, requirements
from tests.test_extraction_pipeline import API, drain


def _patch(actor, row_id, body):
    return actor.client.patch(f"{API}/requirements/{row_id}", json=body)


def test_correcting_a_requirement_keeps_the_original(fake_llm) -> None:
    admin, _, vid = requirement_version(fake_llm)
    row = requirements(admin, vid)[0]
    r = _patch(admin, row["id"], {"requirement_type": "deadline", "description": "Tax clearance"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requirement_type"] == "deadline" and body["review_status"] == "corrected"
    assert body["corrected_value"] == {"requirement_type": "deadline"}  # description unchanged
    assert body["original_value"]["requirement_type"] == "document"
    assert body["reviewed_by_name"] == admin.me["name"]
    assert body["evidence_quote"] == row["evidence_quote"]  # the quote is not editable


@pytest.mark.parametrize(
    "body",
    [
        {"requirement_type": "bogus"},
        {"mandatory_status": "maybe"},
        {"description": ""},
        {"description": None},
        {},
        {"evidence_quote": "rewritten"},
    ],
)
def test_invalid_requirement_patches_are_rejected(fake_llm, body) -> None:
    admin, _, vid = requirement_version(fake_llm)
    assert _patch(admin, requirements(admin, vid)[0]["id"], body).status_code == 422


def test_confirm_reject_and_roles(fake_llm) -> None:
    admin, _, vid = requirement_version(fake_llm)
    row_id = requirements(admin, vid)[0]["id"]
    assert admin.client.post(f"{API}/requirements/{row_id}/reject").json()["review_status"] == "rejected"
    assert admin.client.post(f"{API}/requirements/{row_id}/confirm").json()["review_status"] == "confirmed"
    for role in ("reviewer", "project_manager"):
        other = add_member(admin, f"{role}@example.com", role)
        assert other.client.post(f"{API}/requirements/{row_id}/confirm").status_code == 403
        assert _patch(other, row_id, {"mandatory_status": "informational"}).status_code == 403
    estimator = add_member(admin, "est2@example.com", "estimator")
    assert _patch(estimator, row_id, {"mandatory_status": "informational"}).status_code == 200


def test_a_reviewed_requirement_survives_a_rerun_and_stale_ids_are_404(fake_llm) -> None:
    admin, _, vid = requirement_version(fake_llm)
    row_id = requirements(admin, vid)[0]["id"]
    admin.client.post(f"{API}/requirements/{row_id}/confirm")
    admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    drain()
    rows = requirements(admin, vid)
    assert [r["id"] for r in rows] == [row_id] and rows[0]["review_status"] == "confirmed"
    assert admin.client.post(f"{API}/requirements/{uuid4()}/confirm").status_code == 404
```

In `tests/test_repository_contract.py`, after the `repos["RequirementRepo"].for_version(...)` line add:

```python
        with pytest.raises(NotFound):
            repos["RequirementRepo"].version_id_of(b_ids["RequirementRepo"][0])
        assert repos["RequirementRepo"].fresh(b_ids["RequirementRepo"][0]) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_review_requirements.py -q`
Expected: FAIL (404/405 on the new routes).

- [ ] **Step 3: Implement**

`checklist/schemas.py` (imports `Annotated`, `Literal`, `ConfigDict`, `StringConstraints`, `model_validator`, and `from app.kernel.vocab import MANDATORY_STATUSES, REQUIREMENT_TYPES`):

```python
RequirementType = Literal[*REQUIREMENT_TYPES]
MandatoryStatus = Literal[*MANDATORY_STATUSES]


class RequirementPatch(BaseModel):
    """The fields a reviewer may change. The evidence quote and its location are not editable."""

    model_config = ConfigDict(extra="forbid")

    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = None
    requirement_type: RequirementType | None = None
    mandatory_status: MandatoryStatus | None = None

    @model_validator(mode="after")
    def _check(self) -> RequirementPatch:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be cleared.")
        return self
```

`checklist/repo.py`: add `select` to the sqlalchemy import, `from app.kernel import NotFound`, and the same two methods as `BoqRepo` with `Requirement` in place of `BoqItem` (`version_id_of` raising `NotFound("Requirement not found")`, `fresh` using `populate_existing`).

`checklist/service.py` add imports (`datetime`, `UTC`, `Literal`, `Conflict`, `ValidationFailed`, `audit`, `RequirementPatch`) and:

```python
def version_of(session: Session, ctx: OrgContext, item_id: UUID) -> UUID:
    ctx.require(Permission.REVIEW_DATA)
    return RequirementRepo(session, ctx).version_id_of(item_id)


def review_item(
    session: Session,
    ctx: OrgContext,
    item_id: UUID,
    action: Literal["confirm", "reject", "correct"],
    patch: RequirementPatch | None = None,
) -> RequirementDTO:
    """Call with the extraction lock held. A row a re-run deleted since lookup is `row_replaced`."""
    ctx.require(Permission.REVIEW_DATA)
    row = RequirementRepo(session, ctx).fresh(item_id)
    if row is None:
        raise Conflict(
            "This requirement was replaced by a newer extraction. Reload the list.",
            code="row_replaced",
        )
    fields: list[str] = []
    if action == "correct":
        if patch is None:
            raise ValidationFailed("No changes were given.")
        changes = {
            name: getattr(patch, name)
            for name in patch.model_fields_set
            if getattr(patch, name) != getattr(row, name)
        }
        if not changes:
            return _dto(row)
        for name, value in changes.items():
            setattr(row, name, value)
        row.corrected_value = {**(row.corrected_value or {}), **changes}
        row.review_status = "corrected"
        fields = sorted(changes)
    else:
        row.review_status = "confirmed" if action == "confirm" else "rejected"
    row.reviewed_by, row.reviewed_at = ctx.user_id, datetime.now(UTC)
    audit.record(
        session, ctx, "requirement", row.id, f"review_{row.review_status}",
        {"status": row.review_status, "fields": fields},
    )  # fmt: skip
    session.flush()
    return _dto(row)
```

`checklist/public.py`: export `RequirementPatch`, `review_item`, `version_of`.

`routers/review.py`: add `from app.modules.checklist import public as checklist` and

```python
def _requirement(session, ctx, row_id: UUID, action, patch=None):
    version_id = checklist.version_of(session, ctx, row_id)
    pipeline.lock_runs(session, ctx, version_id, "requirements")
    dto = checklist.review_item(session, ctx, row_id, action, patch)
    return with_reviewer_names(session, ctx, [dto])[0]


@router.patch("/requirements/{requirement_id}", response_model=checklist.RequirementDTO)
def correct_requirement(
    requirement_id: UUID, body: checklist.RequirementPatch, ctx: Ctx, session: DbSession
):
    return _requirement(session, ctx, requirement_id, "correct", body)


@router.post("/requirements/{requirement_id}/confirm", response_model=checklist.RequirementDTO)
def confirm_requirement(requirement_id: UUID, ctx: Ctx, session: DbSession):
    return _requirement(session, ctx, requirement_id, "confirm")


@router.post("/requirements/{requirement_id}/reject", response_model=checklist.RequirementDTO)
def reject_requirement(requirement_id: UUID, ctx: Ctx, session: DbSession):
    return _requirement(session, ctx, requirement_id, "reject")
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_review_requirements.py tests/test_review_boq.py tests/test_repository_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat: review requirements (correct, confirm, reject)"
```

---

### Task 8: Cross-tenant sweep covers the review routes

**Files:**
- Modify: `tests/test_fitness_functions.py`
- Modify: `tests/review_helpers.py` (add `seed_review_rows`)

**Interfaces:**
- Produces: `review_helpers.seed_review_rows(actor, version_id, job_id) -> dict[str, str]` returning `{"boq_item_id": ..., "requirement_id": ...}` for rows owned by that actor's organisation.

- [ ] **Step 1: Write the failing change (extend F1)**

Append to `tests/review_helpers.py`:

```python
def seed_review_rows(actor: Actor, version_id: str, job_id: str) -> dict[str, str]:
    """Give an organisation one BoQ line and one requirement without running a worker job, so
    sweeps of the review routes have real rows to be refused. Uses the ingest job's id for the
    two runs (the (job_id, kind) pair is free)."""
    from uuid import UUID

    from sqlalchemy import select

    from app.db.session import session_scope
    from app.kernel import OrgContext, Role
    from app.modules.checklist import public as checklist
    from app.modules.checklist.models import Requirement
    from app.modules.estimating import public as estimating
    from app.modules.estimating.models import BoqItem
    from app.modules.pipeline.models import ExtractionRun

    ctx = OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)
    with session_scope() as s:
        for kind in ("boq", "requirements"):
            run = ExtractionRun(
                organisation_id=ctx.organisation_id,
                document_version_id=UUID(version_id),
                job_id=UUID(job_id),
                kind=kind,
            )
            s.add(run)
            s.flush()
            if kind == "boq":
                estimating.replace_unreviewed(
                    s, ctx, run.document_version_id, run.id,
                    [{"item_no": "1", "description": "seeded-b-line"}],
                )  # fmt: skip
            else:
                checklist.replace_unreviewed(
                    s, ctx, run.document_version_id, run.id,
                    [{"description": "seeded-b-rule", "requirement_type": "other",
                      "mandatory_status": "mandatory", "evidence_quote": "seeded-b-quote"}],
                )  # fmt: skip
        return {
            "boq_item_id": str(s.scalar(select(BoqItem.id).where(BoqItem.organisation_id == ctx.organisation_id))),
            "requirement_id": str(s.scalar(select(Requirement.id).where(Requirement.organisation_id == ctx.organisation_id))),
        }
```

In `tests/test_fitness_functions.py`:

1. Import: `from tests.review_helpers import seed_review_rows`.
2. Add to `REQUESTS`:

```python
    ("PATCH", "/api/v1/boq-items/{boq_item_id}"): lambda: {"json": {"description": "hijacked"}},
    ("PATCH", "/api/v1/requirements/{requirement_id}"): lambda: {
        "json": {"description": "hijacked"}
    },
```
3. In `test_f1_every_route_with_an_id_refuses_another_organisations_data`, after `assert process_one(handlers.HANDLERS) is True` add `seeded = seed_review_rows(org_b, uploaded["version"]["id"], str(uploaded["job_id"]))`; add `**seeded,` to the `known` dict; extend `forbidden` with `"seeded-b-line", "seeded-b-rule"`; raise the final route-count assertion from `>= 18` to `>= 27` (9 new id routes: PATCH/confirm/reject for both kinds, plus tender requirements, version detail, and the pages routes already counted: recount by running the test once and set the floor to the printed `swept` minus nothing; the assertion's purpose is "no route silently skipped", the equality with `schema_count` is the real guard); and at the end of the test, with the other "B is intact" assertions:

```python
    b_lines = org_b.client.get(f"/api/v1/document-versions/{known['version_id']}/boq-items").json()
    assert [(l["description"], l["review_status"]) for l in b_lines] == [("seeded-b-line", "unreviewed")]
    b_rules = org_b.client.get(f"/api/v1/document-versions/{known['version_id']}/requirements").json()
    assert [(r["description"], r["review_status"]) for r in b_rules] == [("seeded-b-rule", "unreviewed")]
```

- [ ] **Step 2: Run to verify it fails first, then passes**

Run: `uv run pytest tests/test_fitness_functions.py -q`
Expected before the edits to the test file: FAIL (`add {'boq_item_id', 'requirement_id'} to the F1 id registry`). After the edits: PASS, and the new routes are swept with real rows to refuse.

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS. If `test_f1_lists_never_mix_organisations` or `test_every_scoped_repository_is_exercised` fail, fix the test registries, not the app.

- [ ] **Step 4: Commit**

```bash
git add tests
git commit -m "test: extend the cross-tenant sweep to the review routes with real rows"
```

---

### Task 9: Tender-wide requirements list

**Files:**
- Modify: `app/modules/checklist/repo.py` (`for_versions`), `service.py` (`list_for_versions`), `public.py`
- Modify: `app/api/routers/review.py` (route)
- Modify: `tests/test_repository_contract.py`
- Test: `tests/test_tender_requirements.py` (create)

**Interfaces:**
- Consumes: `documents.list_documents(session, ctx, tender_id) -> list[DocumentDTO]` (each has `current_version: VersionDTO | None`).
- Produces: `checklist.list_for_versions(session, ctx, version_ids, review_status=None, requirement_type=None, limit=200, offset=0) -> list[RequirementDTO]`; `GET /api/v1/tenders/{tender_id}/requirements?review_status=&requirement_type=&limit=&offset=` returning only requirements of each document's **current** version.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tender_requirements.py`:

```python
"""Tender-wide requirements: current versions only, filters, paging, tenancy."""

from __future__ import annotations

from tests.conftest import make_pdf, make_tender, register, upload
from tests.review_helpers import requirement_version, requirements
from tests.test_extraction_pipeline import API, CLAUSE, drain, req_json

CLAUSE_2 = "Tenderers must attend the compulsory site meeting on Friday."


def test_lists_current_versions_only_and_filters(fake_llm) -> None:
    admin, tid, vid = requirement_version(fake_llm)
    url = f"{API}/tenders/{tid}/requirements"
    rows = admin.client.get(url).json()
    assert [r["document_version_id"] for r in rows] == [vid]

    doc_id = admin.client.get(f"{API}/tenders/{tid}/documents").json()[0]["id"]
    fake_llm([req_json(CLAUSE_2, "meeting")])
    new = admin.client.post(
        f"{API}/documents/{doc_id}/versions",
        files={"file": ("t2.pdf", make_pdf([CLAUSE_2]), "application/pdf")},
    )
    assert new.status_code == 201, new.text
    drain()
    rows = admin.client.get(url).json()
    assert len(rows) == 1 and rows[0]["document_version_id"] == new.json()["version"]["id"]
    assert rows[0]["requirement_type"] == "meeting"

    assert admin.client.get(url, params={"requirement_type": "meeting"}).json() == rows
    assert admin.client.get(url, params={"requirement_type": "deadline"}).json() == []
    assert admin.client.get(url, params={"review_status": "confirmed"}).json() == []
    assert admin.client.get(url, params={"requirement_type": "bogus"}).status_code == 422
    assert admin.client.get(url, params={"limit": 0}).status_code == 422


def test_a_tender_with_no_documents_is_an_empty_list() -> None:
    admin = register("empty@example.com")
    tid = make_tender(admin)
    assert admin.client.get(f"{API}/tenders/{tid}/requirements").json() == []


def test_requirements_helper_matches_version_list(fake_llm) -> None:
    admin, tid, vid = requirement_version(fake_llm)
    assert admin.client.get(f"{API}/tenders/{tid}/requirements").json() == requirements(admin, vid)
```

(`upload` and `CLAUSE` are imported for clarity of the fixtures; remove any unused import ruff reports.)

In `tests/test_repository_contract.py` after the `for_version` assertions add:

```python
        assert repos["RequirementRepo"].for_versions([version_b], None, None, 50, 0) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_tender_requirements.py -v`
Expected: FAIL (404 on the new route).

- [ ] **Step 3: Implement**

`checklist/repo.py`:

```python
    def for_versions(
        self,
        version_ids: Sequence[UUID],
        review_status: str | None,
        requirement_type: str | None,
        limit: int,
        offset: int,
    ) -> Sequence[Requirement]:
        stmt = self._select().where(Requirement.document_version_id.in_(version_ids))
        if review_status:
            stmt = stmt.where(Requirement.review_status == review_status)
        if requirement_type:
            stmt = stmt.where(Requirement.requirement_type == requirement_type)
        stmt = (
            stmt.order_by(Requirement.source_order, Requirement.position, Requirement.id)
            .limit(limit)
            .offset(offset)
        )
        return self.session.scalars(stmt).all()
```

`checklist/service.py`:

```python
def list_for_versions(
    session: Session,
    ctx: OrgContext,
    version_ids: Sequence[UUID],
    review_status: str | None = None,
    requirement_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[RequirementDTO]:
    """Requirements across several document versions (the caller picks the current ones)."""
    ctx.require(Permission.READ)
    if not version_ids:
        return []
    limit = max(1, min(limit, 1000))
    repo = RequirementRepo(session, ctx)
    rows = repo.for_versions(version_ids, review_status, requirement_type, limit, max(0, offset))
    return [_dto(r) for r in rows]
```

`checklist/public.py`: export `list_for_versions`.

`routers/review.py` add (`from typing import Literal`, `from fastapi import Query`, `from app.kernel.vocab import REQUIREMENT_TYPES`, `from app.modules.documents import public as documents`):

```python
@router.get("/tenders/{tender_id}/requirements", response_model=list[checklist.RequirementDTO])
def tender_requirements(
    tender_id: UUID,
    ctx: Ctx,
    session: DbSession,
    review_status: Literal["unreviewed", "confirmed", "corrected", "rejected"] | None = None,
    requirement_type: Literal[*REQUIREMENT_TYPES] | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """The checklist: requirements of every document's current version in this tender."""
    docs = documents.list_documents(session, ctx, tender_id)  # NotFound for another organisation
    version_ids = [d.current_version.id for d in docs if d.current_version]
    rows = checklist.list_for_versions(
        session, ctx, version_ids, review_status, requirement_type, limit, offset
    )
    return with_reviewer_names(session, ctx, rows)
```

- [ ] **Step 4: Run to verify they pass (including F1, which now sweeps this route)**

Run: `uv run pytest tests/test_tender_requirements.py tests/test_fitness_functions.py tests/test_repository_contract.py -q`
Expected: PASS. If the F1 route-count floor trips, set it to the number the failure message prints for `schema_count`.

- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat: tender-wide requirements list for the checklist page"
```

---

### Task 10: Version detail route and sheet row window

**Files:**
- Modify: `app/api/routers/documents.py` (version route; page route params)
- Modify: `app/modules/knowledge/service.py` (`get_page` window)
- Test: `tests/test_page_window.py` (create)

**Interfaces:**
- Produces: `GET /api/v1/document-versions/{version_id}` returning `VersionDTO`; `GET /api/v1/document-versions/{version_id}/pages/{page_number}?row_from=&row_to=` slicing **sheet** tables to the inclusive 1-based Excel row range `[row_from, row_to]` (`first_row` is updated; non-sheet tables untouched; a window larger than 5000 rows or `row_to < row_from` is 422).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_page_window.py`:

```python
"""Version detail and the sheet row window."""

from __future__ import annotations

import pytest

from tests.conftest import make_tender, make_xlsx, register, upload
from tests.review_helpers import boq_version
from tests.test_extraction_pipeline import API, drain


def _sheet_version():
    admin = register("sheet@example.com")
    tid = make_tender(admin)
    rows = [["Item", "Description", "Unit", "Quantity"]] + [
        [f"{n}", f"Line {n}", "m", f"{n}"] for n in range(1, 31)
    ]
    body = upload(admin, tid, make_xlsx(rows), "big.xlsx", kind="boq").json()
    drain()
    return admin, body["version"]["id"]


def test_version_detail_matches_the_list_entry() -> None:
    admin, tid, vid = boq_version()
    r = admin.client.get(f"{API}/document-versions/{vid}")
    assert r.status_code == 200
    doc = admin.client.get(f"{API}/tenders/{tid}/documents").json()[0]
    assert r.json() == doc["current_version"]
    assert r.json()["job_id"] and r.json()["processing_status"].startswith("ready")


def test_row_window_slices_a_sheet() -> None:
    admin, vid = _sheet_version()
    url = f"{API}/document-versions/{vid}/pages/1"
    whole = admin.client.get(url).json()["tables"][0]
    assert whole["first_row"] == 1 and len(whole["rows"]) == 31
    part = admin.client.get(url, params={"row_from": 10, "row_to": 12}).json()["tables"][0]
    assert part["first_row"] == 10 and part["rows"] == whole["rows"][9:12]
    only_from = admin.client.get(url, params={"row_from": 30}).json()["tables"][0]
    assert only_from["first_row"] == 30 and len(only_from["rows"]) == 2


def test_a_window_past_the_end_is_empty_not_an_error() -> None:
    admin, vid = _sheet_version()
    url = f"{API}/document-versions/{vid}/pages/1"
    table = admin.client.get(url, params={"row_from": 500, "row_to": 510}).json()["tables"][0]
    assert table["rows"] == []


@pytest.mark.parametrize(
    "params", [{"row_from": 10, "row_to": 5}, {"row_from": 1, "row_to": 6000}, {"row_from": 0}]
)
def test_bad_windows_are_422(params) -> None:
    admin, vid = _sheet_version()
    assert admin.client.get(f"{API}/document-versions/{vid}/pages/1", params=params).status_code == 422


def test_the_window_leaves_non_sheet_tables_alone() -> None:
    from app.modules.knowledge.service import window_tables

    table = {"kind": "table", "rows": [["a"], ["b"]]}
    assert window_tables([table], 2, 2) == [table]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_page_window.py -v`
Expected: FAIL (405/404 on the version route; `window_tables` missing).

- [ ] **Step 3: Implement**

`knowledge/service.py` (needs `ValidationFailed` from `app.kernel`):

```python
MAX_WINDOW_ROWS = 5000


def window_tables(tables: list[Any], row_from: int | None, row_to: int | None) -> list[Any]:
    """Slice sheet tables to the inclusive 1-based row range. Other tables pass through."""
    if row_from is None and row_to is None:
        return tables
    out: list[Any] = []
    for table in tables:
        if not isinstance(table, dict) or table.get("kind") != "sheet":
            out.append(table)
            continue
        first = int(table.get("first_row", 1))
        rows = table.get("rows", [])
        start = max((row_from or first) - first, 0)
        stop = len(rows) if row_to is None else max(row_to - first + 1, start)
        out.append({**table, "first_row": first + start, "rows": rows[start:stop]})
    return out
```

Change `get_page`:

```python
def get_page(
    session: Session,
    ctx: OrgContext,
    version_id: UUID,
    page_number: int,
    row_from: int | None = None,
    row_to: int | None = None,
) -> PageDetailDTO:
    ctx.require(Permission.READ)
    if row_from is not None and row_to is not None:
        if row_to < row_from or row_to - row_from + 1 > MAX_WINDOW_ROWS:
            raise ValidationFailed(f"Ask for at most {MAX_WINDOW_ROWS} rows, in order.")
    documents.get_version(session, ctx, version_id)
    page = PageRepo(session, ctx).one(version_id, page_number)
    if page is None:
        raise NotFound("Page not found")
    tables = window_tables(page.tables, row_from, row_to)
    return PageDetailDTO(**_page_dto(page).model_dump(), text=page.text, tables=tables)
```

`routers/documents.py`: change `get_page`:

```python
@router.get(
    "/document-versions/{version_id}/pages/{page_number}", response_model=knowledge.PageDetailDTO
)
def get_page(
    version_id: UUID,
    page_number: int,
    ctx: Ctx,
    session: DbSession,
    row_from: Annotated[int | None, Query(ge=1)] = None,
    row_to: Annotated[int | None, Query(ge=1)] = None,
):
    return knowledge.get_page(session, ctx, version_id, page_number, row_from, row_to)
```
and add before `download_file`:

```python
@router.get("/document-versions/{version_id}", response_model=documents.VersionDTO)
def get_version(version_id: UUID, ctx: Ctx, session: DbSession):
    return documents.get_version(session, ctx, version_id)
```
(`Annotated` and `Query` are already imported in that file for the search route; `ValidationFailed` import goes in `knowledge/service.py`'s `from app.kernel import ...` line.)

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_page_window.py tests/test_documents.py tests/test_fitness_functions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "feat: version detail route and sheet row window on page detail"
```

---

### Task 11: Documents and full verification

**Files:**
- Modify: `docs/known-limitations.md`, `docs/plan.md`, `docs/architecture/architecture.md`, `docs/architecture/adr/0006-db-backed-job-queue-and-idempotent-stages.md`

- [ ] **Step 1: Update the docs**

- `docs/known-limitations.md`: delete the four "Fix before or during Slice 4" bullets (section carry-over, list ordering, review updates conditional, comma ambiguity) and replace them with one note: "Fixed in Slice 4 phase 1: section carry-over, `source_order` list ordering, locked review writes, `ambiguous_separator` flag (the value is still read as thousands)." Add under "Documented trade-offs": concurrent edits of one row are last-write-wins (the DTO shows who and when); scanned BoQs have no manual line entry yet; DOCX sources have no rendered viewer. Update the "Last updated" line.
- `docs/plan.md`: in the Slice 4 row append `**Status (date): phase 1 (backend review API) done: review routes, source_order, tender requirements list.**` with today's date and the actual commit range.
- `docs/architecture/architecture.md`: in the `estimating` and `checklist` rows of the module table, name `version_of`, `review_item` and the patch DTOs; add to section 5 (as built) a short paragraph: review writes take `pipeline.lock_runs` then re-read; 404 for unknown ids, 409 `row_replaced` for a row deleted in between; `original_value` immutable, main columns are the effective value, `corrected_value` holds the changed fields. Add the three extract 409 codes.
- `docs/architecture/adr/0006-...md`: append `## Addendum 2026-10-16 (Slice 4)`: review writes serialise with extraction through the same `(version, kind)` run-row lock; the earlier "conditional `WHERE review_status = 'unreviewed'`" idea is dropped because the lock already orders review against extraction, and extraction only ever deletes unreviewed rows.

- [ ] **Step 2: Full verification (fresh run, read the output)**

Run:

```bash
uv run ruff check . && uv run ruff format --check . && uv run lint-imports && uv run pytest -q
```
Expected: ruff clean, import-linter contracts kept, all tests pass. Report the exact pass count in the commit message body. If `ruff format --check` complains, run `uv run ruff format .`, re-run, and include the formatting in this commit.

- [ ] **Step 3: Real-stack smoke (needs Docker and, for requirements, host Ollama)**

From the repo root: `docker compose up --build -d`, register through http://127.0.0.1:8080, upload a synthetic XLSX BoQ, wait for the job, then with the session cookie `PATCH /api/v1/boq-items/{id}` `{"quantity":"12.5"}` and confirm the response and that `GET .../boq-items` shows `corrected`. Note the result in `docs/plan.md`. Skip the requirements half if Ollama is not running and say so.

- [ ] **Step 4: Commit**

```bash
git add docs backend
git commit -m "docs: Slice 4 phase 1 limitations, architecture notes and ADR-0006 addendum"
```

---

## Self-Review

**Spec coverage (spec section 3 and the phase-1 rows of section 1):**
- Review endpoints for BoQ and requirements (PATCH, confirm, reject): Tasks 6, 7.
- `GET /tenders/{id}/requirements`: Task 9. `GET /document-versions/{id}`: Task 10. Page row window: Task 10.
- DTO fields `original_value`, `reviewed_by`, `reviewed_at`, reviewer names: Task 5.
- `original_value` immutable, effective value in main columns, `corrected_value` changed fields: Tasks 6, 7 (tests assert it).
- 404 vs 409 `row_replaced`, lock via `pipeline.lock_runs`, distinct 409 codes: Tasks 1, 6, 7.
- Roles (admin and estimator only), audit with field names only: Tasks 6, 7.
- Decimal text validation, flags on quantity edits, no-op and empty patches: Task 6.
- Module boundaries (router orchestration, vocab in kernel, names via identity facade): Tasks 1, 5, 9.
- Four Slice 3 fixes: section carry (Task 2), `source_order` (Task 4), locked writes (Tasks 6, 7), ambiguous comma (Task 3).
- F1 changes with real rows: Task 8. Contract-test additions: Tasks 5, 6, 7, 9.
- Docs: Task 11. CI schema-drift, `openapi.json`, frontend, Next constraints, PDF.js spike: **phase 2 plan, not here by design.**

**Placeholder scan:** no TBD/TODO. One deliberate runtime-derived number: Task 8 step 1 item 3 tells the executor to run the sweep once and set the route-count floor from `schema_count` (the equality `swept == schema_count` is the real guard, and the floor is a sanity bound).

**Type consistency:** `review_item(session, ctx, item_id, action, patch=None)` is the same signature in both modules; `version_of(session, ctx, item_id)` likewise; `with_reviewer_names(session, ctx, dtos)` returns a list in every use; `source_order(page_number, position)` is the same name in `types.py`, `public.py`, `boq.py` and the tests; run kinds are `"boq"` and `"requirements"` (the values in `KIND_OF_JOB`); `row_replaced` is spelled identically in code and tests.

**Known risk for the executor:** `Literal[*REQUIREMENT_TYPES]` relies on Python 3.11+ star-unpacking in a subscript (the project targets 3.12). If ruff or Pydantic objects, define the Literal explicitly in `kernel/vocab.py` and assert in a test that it equals the tuple.
