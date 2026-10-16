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
