"""BoQ parser: unit cases for the messy inputs, and scoring against committed ground truth."""

from __future__ import annotations

import difflib
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.extraction import public as extraction
from app.modules.knowledge.parsers import parse_document

PACKS = Path(__file__).parent / "fixtures" / "packs"


def _page(rows, *, kind="sheet", number=1, label="BoQ", source="embedded", status="ok", text=""):
    table = {"kind": kind, "rows": rows}
    if kind == "sheet":
        table["first_row"] = 1
    return extraction.PageInput(number, label, text, source, status, [table])


HEADER = ["Item", "Description", "Unit", "Quantity", "Rate", "Amount"]


@pytest.mark.parametrize(
    ("raw", "expected", "lossy"),
    [
        ("1250.0", Decimal("1250.0"), False),
        ("1 250,50", Decimal("1250.50"), False),
        ("1,250.50", Decimal("1250.50"), False),
        ("250,5", Decimal("250.5"), False),
        ("12,500", Decimal("12500"), False),
        ("R 1 200", Decimal("1200"), False),
        ("1e-05", None, True),  # would be rounded by NUMERIC(18,4)
        ("", None, False),
        ("-", None, False),
        ("rate only", None, False),
    ],
)
def test_parse_decimal(raw, expected, lossy) -> None:
    assert extraction.parse_decimal(raw) == (expected, lossy)


def test_units_are_canonical() -> None:
    assert extraction.canon_unit("Metre") == "m"
    assert extraction.canon_unit("No.") == "no"
    assert extraction.canon_unit("LS") == "sum"
    assert extraction.canon_unit("m²") == "m2"
    assert extraction.canon_unit(None) is None


def test_missing_and_rate_only_quantities_are_never_zero() -> None:
    rows = [
        HEADER,
        ["1.1", "Cable 4mm", "m", "", "", ""],
        ["1.2", "Board 63 A (rate only)", "each", "", "", ""],
        ["1.3", "Lamp", "No.", "rate only", "", ""],
        ["1.4", "Cable 6mm", "m", "0", "", ""],
    ]
    items = {i.item_no: i for i in extraction.parse_boq([_page(rows)]).items}
    assert items["1.1"].quantity is None and "missing_quantity" in items["1.1"].flags
    assert items["1.2"].quantity is None and "rate_only" in items["1.2"].flags
    assert items["1.3"].quantity is None and "rate_only" in items["1.3"].flags
    assert items["1.4"].quantity == Decimal("0")  # a printed zero is a real zero
    assert items["1.2"].unit == "no" and "unit_alias" in items["1.2"].flags


def test_title_block_sections_subtotals_and_cell_range() -> None:
    rows = [
        ["Project: Hall wiring", "", "", "", "", ""],
        [],
        HEADER,
        ["", "CABLES", "", "", "", ""],
        ["2.1", "Cable 2.5mm", "Metre", "1 250,5", "12,50", ""],
        ["", "Sub-total", "", "", "", "15 631,25"],
        ["2.2", "Total station survey", "item", "1", "", ""],
    ]
    result = extraction.parse_boq([_page(rows)])
    assert [i.item_no for i in result.items] == [
        "2.1",
        "2.2",
    ]  # subtotal skipped, not "Total station"
    first = result.items[0]
    assert (first.section, first.quantity, first.rate) == (
        "CABLES",
        Decimal("1250.5"),
        Decimal("12.50"),
    )
    assert (first.sheet, first.cell_range) == ("BoQ", "A5:F5")


def test_header_carries_across_pdf_pages() -> None:
    p1 = _page([HEADER, ["1.1", "Cable", "m", "5", "", ""]], kind="table", number=3, label=None)
    p2 = _page([["1.2", "Conduit", "m", "7", "", ""]], kind="table", number=4, label=None)
    result = extraction.parse_boq([p1, p2])
    assert [(i.item_no, i.page_number) for i in result.items] == [("1.1", 3), ("1.2", 4)]
    assert result.boq_pages == {3, 4}


def test_total_rows_with_only_an_amount_are_skipped() -> None:
    rows = [
        HEADER,
        ["1.1", "Cable", "m", "5", "", ""],
        ["", "Total for Section 2", "", "", "", "1 500,00"],
        ["", "Total carried to summary", "", "", "", "9 000,00"],
        ["1.2", "Total station survey", "item", "1", "", ""],
    ]
    result = extraction.parse_boq([_page(rows)])
    assert [i.item_no for i in result.items] == ["1.1", "1.2"]


def test_header_does_not_leak_to_unrelated_or_distant_tables() -> None:
    boq = _page([HEADER, ["1.1", "Cable", "m", "5", "", ""]], kind="table", number=3, label=None)
    wide = [["a", "b", "c", "d", "e", "f"], ["x", "Some text", "y", "9", "z", "w"]]
    # (a) unrelated wide table two pages after the BoQ page
    two_later = _page(wide, kind="table", number=5, label=None)
    result = extraction.parse_boq([boq, two_later])
    assert [i.item_no for i in result.items] == ["1.1"]
    # (c) a gap page without tables breaks the carry
    gap = extraction.PageInput(4, None, "text", "embedded", "ok", [])
    result = extraction.parse_boq([boq, gap, two_later])
    assert [i.item_no for i in result.items] == ["1.1"] and result.boq_pages == {3}


def test_unparsed_rate_is_flagged() -> None:
    result = extraction.parse_boq([_page([HEADER, ["1.1", "Cable", "m", "5", "1e-05", ""]])])
    assert "rate_unparsed" in result.items[0].flags


def test_more_than_four_decimals_is_flagged_not_rounded() -> None:
    result = extraction.parse_boq([_page([HEADER, ["1.1", "Cable", "m", "1e-05", "", ""]])])
    item = result.items[0]
    assert item.quantity is None and "quantity_unparsed" in item.flags
    assert item.raw_quantity == "1e-05"


def test_scanned_boq_needs_manual_entry() -> None:
    text = "Item Description Unit Quantity Rate Amount\n1.1 Cable m 10"
    page = extraction.PageInput(5, None, text, "ocr", "ok", [])
    result = extraction.parse_boq([page])
    assert result.items == []
    assert result.warnings == [{"code": "BOQ_NEEDS_MANUAL_ENTRY", "pages": [5]}]


def test_page_without_a_table_yields_nothing_and_no_warning() -> None:
    page = extraction.PageInput(1, None, "General conditions of tender", "embedded", "ok", [])
    result = extraction.parse_boq([page])
    assert result.items == [] and result.warnings == [] and result.boq_pages == set()


# --- scoring against the committed ground truth (PRD section 13) ------------------------------


def _norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _load(pack: str):
    root = PACKS / pack
    gt = json.loads((root / "ground_truth.json").read_text(encoding="utf-8"))
    predicted = []
    for doc in gt["documents"]:
        if doc["kind"] not in ("boq", "tender_document") or doc["scanned"]:
            continue
        pages = [
            extraction.PageInput(p.page_number, p.label, p.text, p.text_source, p.status, p.tables)
            for p in parse_document(doc["format"], (root / doc["filename"]).read_bytes())
        ]
        predicted += [(doc["filename"], i) for i in extraction.parse_boq(pages).items]
    return gt, predicted


@pytest.mark.parametrize("pack", ["pack01", "pack02", "pack03", "pack04"])
def test_parser_meets_prd_targets_on_ground_truth(pack: str) -> None:
    gt, predicted = _load(pack)
    by_number = {_norm(i.item_no): (doc, i) for doc, i in predicted}
    total = len(gt["boq_items"])
    found = unit_ok = qty_ok = desc_ok = source_ok = 0
    for g in gt["boq_items"]:
        hit = by_number.get(_norm(g["item_number"]))
        if hit is None:
            continue
        _, p = hit
        found += 1
        unit_ok += int(p.unit == g["unit"])
        gq = None if g["quantity"] is None else Decimal(g["quantity"])
        qty_ok += int(p.quantity == gq)
        if gq is None:
            assert p.quantity != Decimal(0), f"{pack} {g['item_number']}: missing became 0"
        desc_ok += int(
            difflib.SequenceMatcher(None, _norm(p.description), _norm(g["description"])).ratio()
            >= 0.9
        )
        src = g["source"]
        source_ok += int(
            (p.sheet == src["sheet"] and p.cell_range == src["cell_range"])
            if src.get("sheet")
            else p.page_number == src["page"]
        )
    assert found / total >= 0.95, f"{pack}: recall {found}/{total}"
    assert unit_ok / found >= 0.95, f"{pack}: unit {unit_ok}/{found}"
    assert qty_ok / found >= 0.95, f"{pack}: quantity {qty_ok}/{found}"
    assert desc_ok / found >= 0.90, f"{pack}: description {desc_ok}/{found}"
    assert source_ok / found >= 0.95, f"{pack}: source {source_ok}/{found}"
    assert len(predicted) <= total * 1.05, f"{pack}: {len(predicted)} predicted for {total}"
