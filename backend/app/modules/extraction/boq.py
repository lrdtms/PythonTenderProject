"""Deterministic BoQ extraction from ingested tables (no LLM, ADR-0004)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal

from .numbers import parse_decimal
from .types import BOQ_TEXT_LIMITS, BoqCandidate, BoqResult, PageInput
from .units import canon_unit

HEADER_WORDS = {
    "item": {
        "item", "item no", "item no.", "item number", "no", "no.", "ref", "ref.", "nr", "number",
    },
    "description": {"description", "details", "work item", "particulars", "item description"},
    "unit": {"unit", "units", "uom"},
    "quantity": {"quantity", "qty", "qty.", "quantities"},
    "rate": {"rate", "unit rate", "unit price", "price", "rate (r)", "rate r"},
    "amount": {"amount", "total", "amount (r)", "total (r)"},
}  # fmt: skip
MAX_HEADER_SEARCH_ROWS = 40
SUBTOTAL = re.compile(
    r"^\s*((sub-?\s?total|grand total|total|section total|page total)\s*(?:[:\-(]|$)|"
    r"(sub-?\s?total|section total|page total)\b|"
    r"carried forward|brought forward|c/f\b|b/f\b|collection\s*$|summary\s*$)",
    re.I,
)
TOTAL_WORD = re.compile(r"^\s*total\b", re.I)
RATE_ONLY = re.compile(r"\brate\s*only\b|^r/o$", re.I)
PROVISIONAL = re.compile(r"\b(provisional\s+sum|prov\.?\s+sum|pc\s+sum)\b", re.I)
SCAN_FIELDS = ("item", "description", "unit", "quantity", "rate", "amount")


def _norm(cell: object) -> str:
    return re.sub(r"\s+", " ", str(cell or "")).strip().lower().rstrip(":")


def _find_header(rows: Sequence[Sequence[str]]) -> tuple[int, dict[str, int]] | None:
    for index, row in enumerate(rows[:MAX_HEADER_SEARCH_ROWS]):
        columns: dict[str, int] = {}
        for position, cell in enumerate(row):
            key = _norm(cell)
            for field, words in HEADER_WORDS.items():
                if key in words and field not in columns:
                    columns[field] = position
        if "description" in columns and ("unit" in columns or "quantity" in columns):
            if len(columns) >= 3:
                return index, columns
    return None


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _get(row: Sequence[str], columns: dict[str, int], field: str) -> str:
    position = columns.get(field)
    if position is None or position >= len(row):
        return ""
    return str(row[position] or "").strip()


def _candidate(
    row: Sequence[str],
    columns: dict[str, int],
    section: str | None,
    page: PageInput,
    table: dict,
    row_index: int,
    width: int,
) -> BoqCandidate:
    description = _get(row, columns, "description")
    raw_unit = _get(row, columns, "unit") or None
    raw_quantity = _get(row, columns, "quantity") or None
    flags: list[str] = []

    unit = canon_unit(raw_unit)
    if raw_unit and _norm(raw_unit) != unit:
        flags.append("unit_alias")

    quantity: Decimal | None = None
    if raw_quantity and RATE_ONLY.search(raw_quantity):
        flags.append("rate_only")
    elif raw_quantity:
        quantity, lossy = parse_decimal(raw_quantity)
        if quantity is None:
            flags.append("quantity_unparsed")
    if RATE_ONLY.search(description) and "rate_only" not in flags:
        flags.append("rate_only")
    if PROVISIONAL.search(description):
        flags.append("provisional_sum")
    if quantity is None and not (
        set(flags) & {"rate_only", "provisional_sum", "quantity_unparsed"}
    ):
        flags.append("missing_quantity")

    raw_rate = _get(row, columns, "rate")
    rate, _ = parse_decimal(raw_rate)
    if raw_rate and rate is None:
        flags.append("rate_unparsed")
    sheet = cell_range = page_number = None
    if table.get("kind") == "sheet":
        sheet = page.label
        excel_row = int(table.get("first_row", 1)) + row_index
        cell_range = f"A{excel_row}:{_column_letter(width - 1)}{excel_row}"
    else:
        page_number = page.page_number
    cand = BoqCandidate(
        section=section,
        item_no=_get(row, columns, "item") or None,
        description=description,
        unit=unit,
        quantity=quantity,
        rate=rate,
        raw_unit=raw_unit,
        raw_quantity=raw_quantity,
        flags=flags,
        page_number=page_number,
        sheet=sheet,
        cell_range=cell_range,
    )
    _clip(cand)
    return cand


def _clip(cand: BoqCandidate) -> None:
    """Fit every short text field to its column; keep the clipped text and flag it."""
    clipped = False
    for name, limit in BOQ_TEXT_LIMITS.items():
        value = getattr(cand, name)
        if isinstance(value, str) and len(value) > limit:
            setattr(cand, name, value[:limit])
            clipped = True
    if clipped:
        cand.flags.append("truncated")


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
