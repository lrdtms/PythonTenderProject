"""store_quotation: supplier find-or-create, re-runs, and what a re-run must never delete."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.suppliers import public as suppliers
from app.modules.suppliers.models import MatchSuggestion, Quotation, Supplier
from tests.quotation_helpers import quotation_context

HEADER = {
    "supplier_name": "SPARKMORE SUPPLIES", "reference": "Q1", "quote_date": "2026-10-20",
    "valid_until": "2026-11-26", "currency": "ZAR", "prices_include_vat": False, "flags": [],
}  # fmt: skip


def row(description: str, sku: str | None = None, price: str = "5.00", order: int = 0) -> dict:
    return {
        "description": description, "sku": sku, "unit": "m", "quantity": Decimal("10"),
        "unit_price": Decimal(price), "raw_unit": "m", "raw_quantity": "10", "raw_price": price,
        "flags": [], "page_number": 1, "sheet": None, "cell_range": None, "source_order": order,
    }  # fmt: skip


def test_creates_the_supplier_quotation_and_items() -> None:
    with quotation_context() as q:
        out = suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id, HEADER,
            [row("Cable A", "SKU-1"), row("Cable B", "SKU-2", order=1)], "file",
        )  # fmt: skip
        assert (out.inserted, out.duplicates_of_reviewed, out.supplier_created) == (2, 0, True)
        supplier = q.session.get(Supplier, out.supplier_id)
        assert supplier.name == "Sparkmore Supplies" and supplier.name_key == "sparkmore supplies"
        quotation = q.session.get(Quotation, out.quotation_id)
        assert (quotation.reference, str(quotation.valid_until), quotation.currency) == (
            "Q1", "2026-11-26", "ZAR",
        )  # fmt: skip
        assert quotation.prices_include_vat is False


def test_normalise_name_ignores_case_punctuation_and_company_suffixes() -> None:
    assert suppliers.normalise_name("Sparkmore Supplies (Pty) Ltd.") == suppliers.normalise_name(
        "SPARKMORE SUPPLIES"
    )


def test_no_supplier_name_falls_back_to_the_file_name_and_is_flagged() -> None:
    with quotation_context() as q:
        out = suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id,
            {**HEADER, "supplier_name": None, "flags": ["NO_SUPPLIER_NAME"]},
            [row("Cable A")], "quote from acme",
        )  # fmt: skip
        assert q.session.get(Supplier, out.supplier_id).name == "Quote From Acme"
        assert "NO_SUPPLIER_NAME" in q.session.get(Quotation, out.quotation_id).flags


def test_the_same_supplier_name_in_another_quotation_reuses_the_supplier() -> None:
    with quotation_context(versions=2) as q:
        a = suppliers.store_quotation(
            q.session, q.ctx, q.versions[0], q.runs[0], HEADER, [row("A")], "f"
        )
        b = suppliers.store_quotation(
            q.session, q.ctx, q.versions[1], q.runs[1],
            {**HEADER, "supplier_name": "Sparkmore Supplies Pty Ltd"}, [row("A")], "f",
        )  # fmt: skip
        assert a.supplier_id == b.supplier_id and not b.supplier_created


def test_a_rerun_replaces_unreviewed_items_and_keeps_the_users_supplier() -> None:
    with quotation_context() as q:
        first = suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id, HEADER, [row("Old", "SKU-1")], "f"
        )
        other = Supplier(organisation_id=q.ctx.organisation_id, name="Another", name_key="another")
        q.session.add(other)
        q.session.flush()
        q.session.get(Quotation, first.quotation_id).supplier_id = other.id  # the user switched it
        q.session.flush()
        again = suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id, HEADER, [row("New", "SKU-9")], "f"
        )
        assert again.quotation_id == first.quotation_id and again.supplier_id == other.id
        assert [i.description for i in q.items()] == ["New"]


def test_a_rerun_keeps_reviewed_items_and_skips_their_duplicates() -> None:
    with quotation_context() as q:
        suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id, HEADER, [row("Kept", "SKU-1")], "f"
        )
        item = q.items()[0]
        item.review_status = "confirmed"
        item.original_value = {"sku": "SKU-1", "description": "Kept", "unit": "m"}
        q.session.flush()
        out = suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id, HEADER,
            [row("Kept", "SKU-1"), row("Extra", "SKU-2")], "f",
        )  # fmt: skip
        assert out.duplicates_of_reviewed == 1 and out.inserted == 1
        assert sorted(i.description for i in q.items()) == ["Extra", "Kept"]


def test_a_rerun_keeps_an_item_that_a_decided_match_refers_to() -> None:
    with quotation_context(with_boq=True) as q:
        suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id, HEADER, [row("Pinned", "SKU-1")], "f"
        )
        item = q.items()[0]
        q.session.add(
            MatchSuggestion(
                organisation_id=q.ctx.organisation_id,
                boq_item_id=q.boq_item_id,
                quotation_item_id=item.id,
                supplier_id=q.session.get(Quotation, item.quotation_id).supplier_id,
                score=Decimal("0.9"),
                classification="clear",
                status="rejected",
            )  # fmt: skip
        )
        q.session.flush()
        suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id, HEADER, [row("Fresh", "SKU-2")], "f"
        )
        assert "Pinned" in [i.description for i in q.items()]


def test_database_allows_one_confirmed_match_per_boq_line_and_supplier() -> None:
    with quotation_context(with_boq=True) as q:
        out = suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id, HEADER,
            [row("A", "SKU-1"), row("B", "SKU-2", order=1), row("C", "SKU-3", order=2)], "f",
        )  # fmt: skip
        a, b, c = q.items()

        def match(item, status: str, score: str) -> MatchSuggestion:
            return MatchSuggestion(
                organisation_id=q.ctx.organisation_id, boq_item_id=q.boq_item_id,
                quotation_item_id=item.id, supplier_id=out.supplier_id,
                score=Decimal(score), classification="clear", status=status,
            )  # fmt: skip

        q.session.add(match(a, "confirmed", "0.9"))
        q.session.flush()
        q.session.add(match(b, "rejected", "0.8"))
        q.session.flush()  # a rejected sibling is fine
        q.session.add(match(c, "confirmed", "0.8"))  # a second confirmed one is not
        with pytest.raises(IntegrityError):
            q.session.flush()
        q.session.rollback()  # the failed flush left the session unusable for the scope's commit


def test_header_less_quotations_with_one_file_name_stay_separate_suppliers() -> None:
    bare = {**HEADER, "supplier_name": None, "flags": ["NO_SUPPLIER_NAME"]}
    with quotation_context(versions=2) as q:
        a = suppliers.store_quotation(
            q.session, q.ctx, q.versions[0], q.runs[0], bare, [row("A")], "quote"
        )
        b = suppliers.store_quotation(
            q.session, q.ctx, q.versions[1], q.runs[1], bare, [row("A")], "quote"
        )
        assert a.supplier_id != b.supplier_id and a.supplier_created and b.supplier_created
        assert q.session.get(Supplier, a.supplier_id).name == "Quote"
        assert q.session.get(Supplier, b.supplier_id).name_key == f"file:{q.versions[1]}"


def test_a_file_name_supplier_never_merges_with_a_header_supplier() -> None:
    bare = {**HEADER, "supplier_name": None, "flags": ["NO_SUPPLIER_NAME"]}
    with quotation_context(versions=2) as q:
        a = suppliers.store_quotation(
            q.session, q.ctx, q.versions[0], q.runs[0], HEADER, [row("A")], "sparkmore supplies"
        )
        b = suppliers.store_quotation(
            q.session, q.ctx, q.versions[1], q.runs[1], bare, [row("A")], "sparkmore supplies"
        )
        assert a.supplier_id != b.supplier_id


def test_suffix_only_names_do_not_merge_with_each_other() -> None:
    with quotation_context(versions=2) as q:
        a = suppliers.store_quotation(
            q.session, q.ctx, q.versions[0], q.runs[0], {**HEADER, "supplier_name": "Co"},
            [row("A")], "f",
        )  # fmt: skip
        b = suppliers.store_quotation(
            q.session, q.ctx, q.versions[1], q.runs[1], {**HEADER, "supplier_name": "Ltd"},
            [row("A")], "f",
        )  # fmt: skip
        assert a.supplier_id != b.supplier_id
        assert q.session.get(Supplier, a.supplier_id).name_key == "co"


def test_a_rerun_flags_agree_with_the_stored_fields() -> None:
    gaps = {**HEADER, "currency": None, "reference": None, "flags": ["NO_CURRENCY", "NO_REFERENCE"]}
    with quotation_context() as q:
        first = suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id, gaps, [row("A")], "f"
        )
        quotation = q.session.get(Quotation, first.quotation_id)
        assert quotation.flags == ["NO_REFERENCE", "NO_CURRENCY"]
        quotation.currency = "USD"  # set by the user after the first run
        q.session.flush()
        suppliers.store_quotation(q.session, q.ctx, q.version_id, q.run_id, gaps, [row("A")], "f")
        assert quotation.currency == "USD" and quotation.flags == ["NO_REFERENCE"]


def test_the_supplier_name_flag_comes_from_the_header_parse() -> None:
    bare = {**HEADER, "supplier_name": None, "flags": ["NO_SUPPLIER_NAME"]}
    with quotation_context() as q:
        out = suppliers.store_quotation(
            q.session, q.ctx, q.version_id, q.run_id, bare, [row("A")], "f"
        )
        assert q.session.get(Quotation, out.quotation_id).flags == ["NO_SUPPLIER_NAME"]
