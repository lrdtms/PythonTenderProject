"""Run records and item stores: tenancy columns, replace-unreviewed, duplicate-of-reviewed."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update

from app.db.session import session_scope
from app.kernel import OrgContext, Role
from app.modules.checklist import public as checklist
from app.modules.checklist.models import Requirement
from app.modules.estimating import public as estimating
from app.modules.estimating.models import BoqItem
from app.modules.pipeline.models import ExtractionRun
from tests.conftest import make_pdf, make_tender, register, upload


def _seed():
    admin = register("store@example.com")
    body = upload(admin, make_tender(admin), make_pdf(["clause"]), "t.pdf").json()
    ctx = OrgContext(UUID(admin.me["user_id"]), UUID(admin.org_id), Role.ADMIN, None)
    return ctx, UUID(body["version"]["id"]), UUID(body["job_id"])


def _run(session, ctx, version_id, job_id, kind):
    run = ExtractionRun(
        organisation_id=ctx.organisation_id,
        document_version_id=version_id,
        job_id=job_id,
        kind=kind,
    )
    session.add(run)
    session.flush()
    return run.id


def _boq(item_no: str, description: str = "Cable") -> dict:
    return {
        "section": "Cables", "item_no": item_no, "description": description, "unit": "m",
        "quantity": Decimal("10.5"), "rate": None, "raw_unit": "Metre", "raw_quantity": "10,5",
        "flags": ["unit_alias"], "page_number": 3, "sheet": None, "cell_range": None,
    }  # fmt: skip


def test_boq_replace_keeps_reviewed_rows_and_skips_their_duplicates() -> None:
    ctx, version_id, job_id = _seed()
    with session_scope() as s:
        run1 = _run(s, ctx, version_id, job_id, "boq")
        first = estimating.replace_unreviewed(
            s, ctx, version_id, run1, [_boq("1.1"), _boq("1.2"), _boq("1.3")]
        )
        assert (first.inserted, first.duplicates_of_reviewed) == (3, 0)
        s.execute(
            update(BoqItem)
            .where(BoqItem.item_no == "1.1")
            .values(review_status="corrected", corrected_value={"quantity": "12"})
        )
    with session_scope() as s:
        job2 = s.scalar(select(ExtractionRun.id).limit(1))
        assert job2 is not None
        again = estimating.replace_unreviewed(
            s, ctx, version_id, job2, [_boq("1.1"), _boq("1.2"), _boq("1.4")]
        )
        assert (again.inserted, again.duplicates_of_reviewed) == (2, 1)
        rows = estimating.list_boq_items(s, ctx, version_id)
        assert sorted(r.item_no for r in rows) == ["1.1", "1.2", "1.4"]
        reviewed = next(r for r in rows if r.item_no == "1.1")
        assert reviewed.review_status == "corrected"
        assert reviewed.quantity == "10.5000"  # Decimal text; the original is untouched


def test_requirements_replace_dedupes_by_quote() -> None:
    ctx, version_id, job_id = _seed()

    def req(quote: str) -> dict:
        return {
            "description": "Submit tax certificate", "requirement_type": "document",
            "mandatory_status": "mandatory", "evidence_quote": quote, "page_number": 2,
            "quote_start": 0, "quote_end": len(quote), "evidence_status": "verified",
            "needs_review": False,
        }  # fmt: skip

    with session_scope() as s:
        run = _run(s, ctx, version_id, job_id, "requirements")
        checklist.replace_unreviewed(s, ctx, version_id, run, [req("Must submit  tax PIN")])
        s.execute(update(Requirement).values(review_status="confirmed"))
    with session_scope() as s:
        run = s.scalar(select(ExtractionRun.id).limit(1))
        res = checklist.replace_unreviewed(
            s, ctx, version_id, run, [req("must submit tax pin"), req("Closing is at 11:00")]
        )
        assert (res.inserted, res.duplicates_of_reviewed) == (1, 1)


def test_items_cannot_point_at_another_versions_run() -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError

    ctx, version_id, job_id = _seed()
    with pytest.raises(IntegrityError), session_scope() as s:
        run = _run(s, ctx, version_id, job_id, "boq")
        s.add(
            BoqItem(
                organisation_id=ctx.organisation_id,
                run_id=run,
                document_version_id=UUID(int=1),  # not this run's version
                description="x",
                position=0,
                original_value={},
            )
        )
        s.flush()


def test_boq_text_limits_match_the_columns() -> None:
    from app.modules.extraction import public as extraction

    for name, limit in extraction.BOQ_TEXT_LIMITS.items():
        assert BoqItem.__table__.c[name].type.length == limit, name


def test_requirement_enums_fit_their_columns() -> None:
    from app.modules.extraction.prompts import MANDATORY_STATUSES, REQUIREMENT_TYPES

    cols = Requirement.__table__.c
    assert max(map(len, REQUIREMENT_TYPES)) <= cols["requirement_type"].type.length
    assert max(map(len, MANDATORY_STATUSES)) <= cols["mandatory_status"].type.length
    for status in ("verified", "evidence_unverified"):
        assert len(status) <= cols["evidence_status"].type.length


def test_oversized_parser_output_is_stored() -> None:
    from app.modules.extraction import public as extraction

    header = ["Item", "Description", "Unit", "Quantity", "Rate", "Amount"]
    rows = [
        header,
        ["", "Notes: All rates shall include for " + "everything required " * 25, "", "", "", ""],
        ["9" * 80, "Trench", "per metre run incl trenching and backfill", "1e999999999",
         "123456789012345", ""],
        ["1.2", "Cable", "m", "0e999999999", "-1e99999999999999999999999999", ""],
    ]  # fmt: skip
    page = extraction.PageInput(1, "S" * 250, "", "embedded", "ok", [{"kind": "sheet",
                                "rows": rows, "first_row": 1}])  # fmt: skip
    cands = [c.as_row() for c in extraction.parse_boq([page]).items]
    ctx, version_id, job_id = _seed()
    with session_scope() as s:
        run = _run(s, ctx, version_id, job_id, "boq")
        res = estimating.replace_unreviewed(s, ctx, version_id, run, cands)
        assert res.inserted == 2
    with session_scope() as s:
        items = estimating.list_boq_items(s, ctx, version_id)
        first = items[0]
        assert first.quantity is None and first.rate is None
        assert first.raw_quantity == "1e999999999"
        assert {"truncated", "quantity_unparsed", "rate_unparsed"} <= set(first.flags)
        assert len(first.section or "") == 300 and len(first.unit or "") == 30
        assert items[1].quantity == "0.0000" and "rate_unparsed" in items[1].flags
