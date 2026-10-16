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


def page(
    text: str, rows: list[list[str]], number: int = 1, source: str = "embedded", kind: str = "table"
):
    table = {"kind": kind, "rows": rows}
    if kind == "sheet":
        table["first_row"] = 1
    return extraction.PageInput(
        number, "Quote 1" if kind == "sheet" else None, text, source, "ok", [table]
    )


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
        "Q33227",
        date(2026, 10, 20),
        date(2026, 11, 26),
        "ZAR",
    )
    assert h.prices_include_vat is False and h.flags == []


def test_reads_the_sheet_style_header_from_the_rows_above_the_table() -> None:
    rows = [
        ["Greenvale Cable and Conduit"],
        ["Quotation Q78533"],
        ["Date: 2026-10-21"],
        ["Valid until: 2026-11-12"],
        ["Currency: ZAR"],
        [],
        HEADER,
        ["1", "Socket", "no", "43", "146"],
    ]
    result = extraction.parse_quotation([page("", rows, kind="sheet")])
    h = result.header
    assert (h.supplier_name, h.reference, h.valid_until, h.currency) == (
        "Greenvale Cable and Conduit",
        "Q78533",
        date(2026, 11, 12),
        "ZAR",
    )
    assert h.prices_include_vat is None and "VAT_UNKNOWN" in h.flags
    assert result.items[0].cell_range == "A8:E8" and result.items[0].sheet == "Quote 1"


def test_missing_header_fields_are_flagged_not_guessed() -> None:
    h = parse([HEADER, ["1", "Cable", "m", "10", "5"]], text="").header
    assert h.supplier_name is None and h.reference is None and h.currency is None
    assert {
        "NO_SUPPLIER_NAME",
        "NO_REFERENCE",
        "NO_QUOTE_DATE",
        "NO_VALIDITY",
        "NO_CURRENCY",
        "VAT_UNKNOWN",
    } <= set(h.flags)


def test_sku_is_lifted_out_of_a_wrapped_description() -> None:
    item = parse([HEADER, ["1", "Main board, 400 A\n[SKU-5078]", "no", "2", "54917.00"]]).items[0]
    assert item.sku == "SKU-5078" and item.description == "Main board, 400 A"


@pytest.mark.parametrize(
    "cell, sku",
    [
        ("LED panel Code: AB-12", "AB-12"),
        ("LED panel [ab-12]", "ab-12"),
        ("LED panel (not a code)", None),
        ("LED panel", None),
    ],
)
def test_sku_variants(cell: str, sku: str | None) -> None:
    assert parse([HEADER, ["1", cell, "no", "1", "5"]]).items[0].sku == sku


@pytest.mark.parametrize(
    "raw, price, flag",
    [
        ("5.00", Decimal("5.00"), None),
        ("R 1 234,50", Decimal("1234.50"), None),
        ("1,500", Decimal("1500"), "ambiguous_separator"),
        ("POA", None, "price_unparsed"),
        ("-", None, "missing_price"),
        ("", None, "missing_price"),
        ("12.34567", None, "price_unparsed"),
    ],
)
def test_prices_are_parsed_or_null_never_zero(
    raw: str, price: Decimal | None, flag: str | None
) -> None:
    item = parse([HEADER, ["1", "Cable", "m", "10", raw]]).items[0]
    assert item.unit_price == price
    if price is None:
        assert item.unit_price != Decimal(0)
    assert (
        (flag in item.flags) if flag else not set(item.flags) & {"price_unparsed", "missing_price"}
    )


def test_quantity_missing_or_unreadable_is_flagged() -> None:
    items = parse([HEADER, ["1", "A", "m", "", "5"], ["2", "B", "m", "ten", "5"]]).items
    assert "missing_quantity" in items[0].flags and items[0].quantity is None
    assert "quantity_unparsed" in items[1].flags and items[1].quantity is None


def test_unit_is_canonical_and_alias_flagged() -> None:
    item = parse([HEADER, ["1", "Cable", "Metres", "10", "5"]]).items[0]
    assert item.unit == "m" and "unit_alias" in item.flags and item.raw_unit == "Metres"


def test_totals_and_blank_rows_are_not_items() -> None:
    rows = [
        HEADER,
        ["1", "Cable", "m", "10", "5"],
        [],
        ["", "Sub-total", "", "", "50"],
        ["", "Total", "", "", "50"],
    ]
    assert [i.description for i in parse(rows).items] == ["Cable"]


def test_a_table_continues_on_the_next_page_without_a_header() -> None:
    first = page("ACME\nQUOTATION Q1", [HEADER, ["1", "A", "m", "1", "1"]], number=1)
    second = extraction.PageInput(
        2, None, "", "embedded", "ok", [{"kind": "table", "rows": [["2", "B", "m", "2", "2"]]}]
    )
    result = extraction.parse_quotation([first, second])
    assert [(i.description, i.page_number) for i in result.items] == [("A", 1), ("B", 2)]


def test_scanned_quotation_is_flagged_for_manual_entry() -> None:
    text = "ACME\nQUOTATION\n# Description Unit Qty Unit price\n1 Cable m 10 5.00"
    scanned = extraction.PageInput(1, None, text, "ocr", "ok", [])
    result = extraction.parse_quotation([scanned])
    assert result.items == [] and result.warnings == [
        {"code": "QUOTE_NEEDS_MANUAL_ENTRY", "pages": [1]}
    ]


def test_no_table_gives_a_warning_not_an_error() -> None:
    result = extraction.parse_quotation(
        [extraction.PageInput(1, None, "Dear sir", "embedded", "ok", [])]
    )
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
    doc = next(
        d
        for d in json.loads((pack / "ground_truth.json").read_text())["documents"]
        if d["filename"] == quote["document"]
    )
    pages = [
        extraction.PageInput(p.page_number, p.label, p.text, p.text_source, p.status, p.tables)
        for p in parse_document(doc["format"], (pack / quote["document"]).read_bytes())
    ]
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


def test_charge_rows_are_not_items() -> None:
    rows = [
        HEADER,
        ["", "VAT", "", "", "7.5"],
        ["", "Delivery", "", "", "150", ""],
        ["", "Discount", "", "", "-5%"],
        ["", "VAT @ 15%", "", "", "30"],
        ["", "Less discount", "", "", "10"],
        ["", "Delivery charge", "", "", "99"],
        ["1", "Cable", "m", "10", "5"],
    ]
    assert [i.description for i in parse(rows).items] == ["Cable"]


def test_a_product_starting_with_a_charge_word_stays_an_item() -> None:
    items = parse([HEADER, ["1", "Delivery van tyre", "no", "4", "900"]]).items
    assert [i.description for i in items] == ["Delivery van tyre"]


def test_address_line_above_the_company_name_is_not_the_supplier() -> None:
    text = "Pretoria Road 5, Sandton\nAcme Electrical (Pty) Ltd\nQUOTATION Q1\nDate: 2026-10-20"
    assert parse([HEADER, ["1", "Cable", "m", "1", "5"]], text).header.supplier_name == (
        "Acme Electrical (Pty) Ltd"
    )


def test_plain_first_line_name_wins_without_a_suffix_line() -> None:
    text = "12 Main Street\nSPARKMORE SUPPLIES\nQUOTATION Q1\nDate: 2026-10-20"
    assert parse([HEADER, ["1", "Cable", "m", "1", "5"]], text).header.supplier_name == (
        "SPARKMORE SUPPLIES"
    )


@pytest.mark.parametrize(
    "name",
    [
        "Main Road Electrical Supplies",
        "Box Packaging (Pty) Ltd",
        "Drive Systems Ltd",
        "Floor Tiles CC",
        "Dr Reddy Pharmacy",
        "Park Street Hardware",
        "2 Way Electrical (Pty) Ltd",
    ],
)
def test_legit_supplier_names_with_address_words_are_chosen(name: str) -> None:
    text = f"{name}\nQUOTATION Q1\nDate: 2026-10-20"
    assert parse([HEADER, ["1", "Cable", "m", "1", "5"]], text).header.supplier_name == name


def test_po_box_alone_is_not_a_supplier() -> None:
    text = "PO Box 12\nQUOTATION Q1\nDate: 2026-10-20"
    assert parse([HEADER, ["1", "Cable", "m", "1", "5"]], text).header.supplier_name is None


@pytest.mark.parametrize("label", ["Less: discount", "Less: Discount 10%", "Add: VAT @ 15%"])
def test_prefixed_charge_rows_with_a_colon_are_not_items(label: str) -> None:
    rows = [HEADER, ["1", "Cable", "m", "10", "5"], ["", label, "", "", "10"]]
    assert [i.description for i in parse(rows).items] == ["Cable"]


# --- final-review fixes: wrapped rows, zero prices, header guesses -----------------------------


def test_sku_on_the_next_row_joins_the_item_above() -> None:
    rows = [HEADER, ["1", "Main board, 400 A", "no", "2", "5"], ["", "[SKU-5078]", "", "", ""]]
    items = parse(rows).items
    assert len(items) == 1
    assert (items[0].description, items[0].sku) == ("Main board, 400 A", "SKU-5078")


def test_wrapped_continuation_text_with_a_sku_joins_the_item_above() -> None:
    rows = [HEADER, ["1", "Main board, 400 A", "no", "2", "5"], ["", "with isolator [SKU-5078]"]]
    items = parse(rows).items
    assert len(items) == 1
    assert (items[0].description, items[0].sku) == ("Main board, 400 A with isolator", "SKU-5078")


def test_lower_case_continuation_without_a_sku_joins_the_item_above() -> None:
    rows = [HEADER, ["1", "Main board", "no", "2", "5"], ["", "with isolator", "", "", ""]]
    items = parse(rows).items
    assert [i.description for i in items] == ["Main board with isolator"]


def test_description_row_before_a_sku_only_figures_row_is_prepended() -> None:
    rows = [HEADER, ["1", "Main board, 400 A"], ["", "[SKU-5078]", "no", "2", "5"]]
    items = parse(rows).items
    assert len(items) == 1
    assert (items[0].description, items[0].sku) == ("Main board, 400 A", "SKU-5078")
    assert items[0].quantity == Decimal(2) and items[0].unit_price == Decimal(5)


def test_description_row_before_a_row_with_an_empty_description_is_prepended() -> None:
    rows = [HEADER, ["", "Main board, 400 A", "", "", ""], ["", "", "no", "2", "5"]]
    assert [i.description for i in parse(rows).items] == ["Main board, 400 A"]


def test_a_real_section_heading_is_still_skipped() -> None:
    rows = [
        HEADER,
        ["", "ELECTRICAL MATERIALS", "", "", ""],
        ["1", "Cable", "m", "10", "5"],
        ["", "LIGHTING", "", "", ""],
        ["2", "Lamp", "no", "4", "9"],
    ]
    assert [i.description for i in parse(rows).items] == ["Cable", "Lamp"]


def test_an_empty_description_falls_back_to_the_sku_and_is_flagged() -> None:
    item = parse([HEADER, ["1", "[SKU-5078]", "no", "2", "5"]]).items[0]
    assert item.description == "SKU-5078" and item.sku == "SKU-5078"
    assert "missing_description" in item.flags


@pytest.mark.parametrize(
    "raw, flag",
    [
        ("0", "zero_price"),
        ("0.00", "zero_price"),
        ("R0,00", "zero_price"),
        ("-50", "negative_price"),
    ],
)
def test_zero_and_negative_prices_are_null_and_flagged(raw: str, flag: str) -> None:
    item = parse([HEADER, ["1", "Cable", "m", "10", raw]]).items[0]
    assert item.unit_price is None and item.raw_price == raw and flag in item.flags


def test_zero_quantity_is_kept_and_flagged() -> None:
    item = parse([HEADER, ["1", "Cable", "m", "0", "5"]]).items[0]
    assert item.quantity == Decimal(0) and "zero_quantity" in item.flags


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Currency: USD", "USD"),
        ("currency: zar", "ZAR"),
        ("All prices in ZAR", "ZAR"),
        ("Bank: FNB\nAccount currency ZAR", "ZAR"),
        ("Bank details\nBranch ZAR 250655\nAccount 123", None),
    ],
)
def test_currency_is_read_case_insensitively_and_not_guessed(
    text: str, expected: str | None
) -> None:
    header = parse([HEADER, ["1", "Cable", "m", "1", "5"]], f"ACME SUPPLIES\n{text}").header
    assert header.currency == expected
    assert ("NO_CURRENCY" in header.flags) == (expected is None)


def test_headings_on_one_line_do_not_feed_the_header_fields() -> None:
    text = (
        "ACME SUPPLIES\n# Description Unit Qty Unit price\n1 Brackets for quote 2 no 5.00\n"
        "Delivery date: 2026-11-01"
    )
    header = parse([HEADER, ["1", "Brackets", "no", "2", "5"]], text).header
    assert header.reference is None and header.quote_date is None
    assert {"NO_REFERENCE", "NO_QUOTE_DATE"} <= set(header.flags)


def test_reference_must_start_a_line() -> None:
    text = "ACME SUPPLIES\nPlease quote 2 weeks lead time\nQUOTATION Q9"
    assert parse([HEADER, ["1", "Cable", "m", "1", "5"]], text).header.reference == "Q9"


@pytest.mark.parametrize("label", ["Expiry date", "Delivery date", "Valid date", "Due date"])
def test_other_dates_are_not_the_quote_date(label: str) -> None:
    text = f"ACME SUPPLIES\nQUOTATION Q1\n{label}: 2026-12-01\nDate: 2026-10-20"
    header = parse([HEADER, ["1", "Cable", "m", "1", "5"]], text).header
    assert header.quote_date == date(2026, 10, 20)
    only = f"ACME SUPPLIES\nQUOTATION Q1\n{label}: 2026-12-01"
    assert parse([HEADER, ["1", "Cable", "m", "1", "5"]], only).header.quote_date is None
