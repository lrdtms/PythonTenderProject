"""Deterministic quotation extraction from ingested pages (no LLM, FR-55)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime

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
VAT_EXCLUDED = re.compile(
    r"\b(?:exclud\w*|excl\.?|ex\.?)\s*(?:of\s*)?(?:value[- ]added tax|vat)", re.I
)
VAT_INCLUDED = re.compile(r"\b(?:includ\w*|incl\.?)\s*(?:of\s*)?(?:value[- ]added tax|vat)", re.I)
NOT_A_NAME = re.compile(
    r"synthetic test|^page\s*\d+|^\s*quotation\b|^\s*quote\b|^\s*date\b|valid|currency|"
    r"^\s*prices?\b|subject to|^\s*(tel|phone|email|e-mail|fax|www)\b|@|vat\s*(no|number|reg)|"
    r"^\s*(to|attn|attention)\b",
    re.I,
)
ADDRESS_LINE = re.compile(
    r"^\s*\d|\b(street|st|road|rd|avenue|ave|drive|dr|box|p\.o\.|postal|suite|floor)\b", re.I
)
COMPANY_SUFFIX = re.compile(r"\b(pty|ltd|cc|inc|limited|co)\b", re.I)
CHARGE_WORD = r"vat|delivery|freight|discount|rounding|transport|handling|surcharge|carriage|levy"
# A charge line: starts with a charge word (optionally "less"/"add"), or is only that word plus
# a percentage, amount, "charge" or "fee".
CHARGE_ROW = re.compile(
    rf"^\s*(?:(?:less|add|plus)\s+)?(?:{CHARGE_WORD})\b(?:\s*(?:@|:|-)?\s*[-+R\d.,%()\s]*|\s+(?:charges?|fees?)\b.*)?$",
    re.I,
)
BRACKET_SKU = re.compile(r"\[\s*((?:SKU[\s:\-]*)?[A-Za-z0-9][A-Za-z0-9\-_/.]{1,40})\s*\]\s*$", re.I)
LABEL_SKU = re.compile(
    r"\b(?:sku|code|part\s*no\.?|product\s*code)\s*[:#]\s*([A-Za-z0-9][\w\-/.]{1,40})\s*$", re.I
)


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


def _preamble_lines(
    page: PageInput, rows: list[list[str]], header_row: int, table: dict
) -> list[str]:
    """Text above the item table: the rows above it on a sheet, the page text before the column
    headings on a PDF."""
    if table.get("kind") == "sheet":
        return [
            _clean(" ".join(str(c) for c in row if str(c or "").strip()))
            for row in rows[:header_row]
        ]
    lines = [_clean(line) for line in page.text.splitlines()]
    for index, line in enumerate(lines):
        if _norm(line) in HEADER_WORDS["item"] | HEADER_WORDS["description"]:
            return lines[:index]
    return lines


def _read_header(lines: list[str]) -> QuotationHeader:
    header = QuotationHeader()
    blob = "\n".join(line for line in lines if line)
    candidates = [
        line
        for line in lines
        if line
        and re.search(r"[^\W\d_]", line)
        and not NOT_A_NAME.search(line)
        and not ADDRESS_LINE.search(line)
        and len(line) <= 120
    ]
    suffixed = next((line for line in candidates[:8] if COMPANY_SUFFIX.search(line)), None)
    header.supplier_name = suffixed or (candidates[0] if candidates else None)
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


def _candidate(row, columns, page, table, row_index, width, order) -> QuotationCandidate:  # noqa: ANN001
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
        if carried is not None and (
            last_page is None or page.page_number not in (last_page, last_page + 1)
        ):
            carried = None
        if page.text_source == "ocr" and not page.tables:
            words = set(re.findall(r"[a-z]+", page.text.lower()))
            hits = sum(
                1 for f in ("description", "unit", "quantity", "price") if HEADER_WORDS[f] & words
            )
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
                if TOTAL_WORD.match(description) and not (
                    _get(row, columns, "unit") or _get(row, columns, "quantity")
                ):
                    continue
                if CHARGE_ROW.match(description):
                    continue  # VAT, delivery, discount and similar charge lines
                if not any(_get(row, columns, f) for f in ("unit", "quantity", "price")):
                    continue  # a heading line inside the table
                result.items.append(
                    _candidate(
                        row,
                        columns,
                        page,
                        table,
                        offset,
                        width,
                        source_order(page.page_number, table_idx * 10_000 + offset),
                    )  # fmt: skip
                )
                result.quote_pages.add(page.page_number)
    if not header_read:
        result.header = _read_header([])
    if scanned:
        result.warnings.append({"code": "QUOTE_NEEDS_MANUAL_ENTRY", "pages": scanned})
    elif not result.items:
        result.warnings.append({"code": "NO_QUOTATION_FOUND"})
    return result
