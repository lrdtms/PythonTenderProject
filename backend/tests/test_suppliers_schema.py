"""The Slice 5a tables: tenancy shape and the constraints later phases rely on."""

from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.db.base import Base
from app.infrastructure.model_registry import import_all_models

import_all_models()

TABLES = ("suppliers", "quotations", "quotation_items", "match_suggestions")


def _table(name: str):
    return Base.metadata.tables[name]


def _unique_sets(table) -> set[frozenset[str]]:
    out = {
        frozenset(c.name for c in u.columns)
        for u in table.constraints
        if isinstance(u, UniqueConstraint)
    }
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
    assert frozenset({"organisation_id", "id", "document_version_id"}) in _unique_sets(
        _table("quotations")
    )


def test_supplier_name_is_unique_per_organisation() -> None:
    assert frozenset({"organisation_id", "name_key"}) in _unique_sets(_table("suppliers"))


def test_one_quotation_per_document_version() -> None:
    assert frozenset({"organisation_id", "document_version_id"}) in _unique_sets(
        _table("quotations")
    )


def test_a_pair_is_suggested_once() -> None:
    assert frozenset({"boq_item_id", "quotation_item_id"}) in _unique_sets(
        _table("match_suggestions")
    )


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
