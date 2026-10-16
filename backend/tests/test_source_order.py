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
