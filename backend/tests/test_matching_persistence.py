"""Matching persistence: replace undecided suggestions, keep decided ones."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.modules.estimating.models import BoqItem
from app.modules.suppliers import public as suppliers
from app.modules.suppliers.models import MatchSuggestion
from app.modules.suppliers.repo import MatchRepo
from tests.quotation_helpers import QuotationContext, quotation_context

ROWS = [
    {"description": "Cable 4mm", "unit": "m", "unit_price": "5", "source_order": 0},
    {"description": "Board 63 A", "unit": "each", "unit_price": "90", "source_order": 1},
]


def _boq(qc: QuotationContext) -> list[BoqItem]:
    stmt = select(BoqItem).order_by(BoqItem.position)
    return list(qc.session.scalars(stmt.where(BoqItem.organisation_id == qc.ctx.organisation_id)))


def _inputs(qc: QuotationContext) -> list[suppliers.BoqInput]:
    return [suppliers.BoqInput(b.id, b.item_no, b.description, b.unit) for b in _boq(qc)]


def _run(qc: QuotationContext, versions=None, boq=None) -> suppliers.MatchResult:
    return suppliers.match_tender(
        qc.session, qc.ctx, qc.tender_id, _inputs(qc) if boq is None else boq,
        qc.versions if versions is None else versions, None,
    )  # fmt: skip


def _rows(qc: QuotationContext, status: str | None = None) -> list[MatchSuggestion]:
    stmt = select(MatchSuggestion)
    if status:
        stmt = stmt.where(MatchSuggestion.status == status)
    qc.session.flush()
    return list(qc.session.scalars(stmt))


def test_match_tender_stores_suggestions_with_the_quotation_supplier() -> None:
    with quotation_context(versions=2, with_boq=True, quotation_rows=ROWS) as qc:
        result = _run(qc)
        rows = _rows(qc)
        assert result.suggested == len(rows) > 0
        assert {r.supplier_id for r in rows} == set(qc.supplier_ids)
        for r in rows:
            assert isinstance(r.score, Decimal) and r.classification in ("clear", "ambiguous")
            assert r.status == "suggested" and "rank" in r.evidence
            assert "Cable" not in str(r.evidence) and "Board" not in str(r.evidence)


def test_a_rerun_replaces_suggested_rows_and_keeps_decided_ones() -> None:
    with quotation_context(versions=1, with_boq=True, quotation_rows=ROWS) as qc:
        _run(qc)
        first = _rows(qc, "suggested")
        old_ids = {r.id for r in first}
        assert len(first) >= 2  # the fixture is deterministic
        confirmed, rejected = first[0], first[1]
        confirmed.status = "confirmed"
        rejected.status = "rejected"
        qc.session.flush()
        result = _run(qc)
        assert result.kept_decided == 2
        assert result.removed_suggested == len(first) - result.kept_decided
        new = _rows(qc, "suggested")
        assert not {r.id for r in new} & old_ids
        assert {r.id for r in _rows(qc, "confirmed")} == {confirmed.id}
        assert {r.id for r in _rows(qc, "rejected")} == {rejected.id}


def test_decided_pairs_and_confirmed_slots_are_not_suggested_again() -> None:
    with quotation_context(versions=2, with_boq=True, quotation_rows=ROWS) as qc:
        _run(qc)
        rows = _rows(qc, "suggested")
        target = rows[0]
        others = [r for r in rows if r.boq_item_id == target.boq_item_id]
        target.status = "confirmed"
        qc.session.flush()
        _run(qc)
        after = _rows(qc, "suggested")
        assert not [
            r for r in after
            if r.boq_item_id == target.boq_item_id and r.supplier_id == target.supplier_id
        ]  # fmt: skip
        assert any(o.supplier_id != target.supplier_id for o in others)  # a second supplier
        assert [
            r for r in after
            if r.boq_item_id == target.boq_item_id and r.supplier_id != target.supplier_id
        ]  # fmt: skip
        # a rejected pair is never suggested again
        assert after
        pair = (after[0].boq_item_id, after[0].quotation_item_id)
        after[0].status = "rejected"
        qc.session.flush()
        _run(qc)
        assert pair not in {(r.boq_item_id, r.quotation_item_id) for r in _rows(qc, "suggested")}


def test_rejected_items_missing_boq_and_other_versions_are_ignored() -> None:
    with quotation_context(versions=2, with_boq=True, quotation_rows=ROWS) as qc:
        # only the first version counts
        _run(qc, versions=[qc.versions[0]])
        assert {r.supplier_id for r in _rows(qc)} == {qc.supplier_ids[0]}
        # a rejected quotation item is not matched
        for item in qc.items():
            item.review_status = "rejected"
        qc.session.flush()
        assert _run(qc, versions=[qc.versions[0]]).suggested == 0
        # a BoQ line that is not passed is ignored
        result = _run(qc, versions=[qc.versions[1]], boq=_inputs(qc)[:1])
        assert result.suggested > 0
        assert {r.boq_item_id for r in _rows(qc, "suggested")} == {_boq(qc)[0].id}


def test_decided_boq_item_ids_returns_only_decided_lines() -> None:
    with quotation_context(versions=1, with_boq=True, quotation_rows=ROWS) as qc:
        _run(qc)
        rows = _rows(qc, "suggested")
        assert suppliers.decided_boq_item_ids(qc.session, qc.ctx) == set()
        rows[0].status = "confirmed"
        rows[0].decided_by, rows[0].decided_at = qc.ctx.user_id, datetime.now(UTC)
        qc.session.flush()
        assert suppliers.decided_boq_item_ids(qc.session, qc.ctx) == {rows[0].boq_item_id}


def test_empty_inputs_do_not_fail() -> None:
    with quotation_context(versions=1, with_boq=True) as qc:
        assert _run(qc, boq=[]) == suppliers.MatchResult(0, 0, 0)
        assert _run(qc, versions=[]) == suppliers.MatchResult(0, 0, 0)
        assert _run(qc) == suppliers.MatchResult(0, 0, 0)  # quotation has no items


def test_the_tender_lock_can_be_taken_twice_in_one_transaction() -> None:
    with quotation_context() as qc:
        repo = MatchRepo(qc.session, qc.ctx)
        repo.lock_tender(qc.tender_id)
        repo.lock_tender(qc.tender_id)


def _confirm(qc: QuotationContext, row: MatchSuggestion) -> None:
    row.status, row.decided_by, row.decided_at = "confirmed", qc.ctx.user_id, datetime.now(UTC)
    qc.session.flush()


def _released_events(qc: QuotationContext) -> list:
    from app.modules.audit.models import AuditEvent

    stmt = select(AuditEvent).where(AuditEvent.action == "match_released_stale")
    return list(qc.session.scalars(stmt))


def test_a_confirmed_match_of_a_quotation_that_is_no_longer_current_is_released() -> None:
    with quotation_context(versions=2, with_boq=True, quotation_rows=ROWS) as qc:
        _run(qc)
        rows = _rows(qc, "suggested")
        mine = rows[0]
        theirs = next(
            r
            for r in rows
            if r.boq_item_id == mine.boq_item_id and r.supplier_id != mine.supplier_id
        )
        _confirm(qc, mine)
        _confirm(qc, theirs)
        keep = [
            v for v, s in zip(qc.versions, qc.supplier_ids, strict=True) if s == theirs.supplier_id
        ]
        _run(qc, versions=keep)  # my supplier's version is superseded
        qc.session.expire_all()
        assert qc.session.get(MatchSuggestion, mine.id) is None  # released, then replaced
        assert qc.session.get(MatchSuggestion, theirs.id).status == "confirmed"
        assert [e.event_metadata for e in _released_events(qc)] == [{"count": 1}]
        assert not [r for r in _rows(qc) if r.supplier_id == mine.supplier_id]


def test_a_live_confirmed_match_is_not_released() -> None:
    with quotation_context(versions=2, with_boq=True, quotation_rows=ROWS) as qc:
        _run(qc)
        mine = _rows(qc, "suggested")[0]
        _confirm(qc, mine)
        _run(qc)
        assert qc.session.get(MatchSuggestion, mine.id).status == "confirmed"
        assert _released_events(qc) == []


def test_release_never_touches_another_organisations_rows() -> None:
    from uuid import uuid4

    from app.kernel import OrgContext, Role

    with quotation_context(versions=1, with_boq=True, quotation_rows=ROWS) as qc:
        _run(qc)
        mine = _rows(qc, "suggested")[0]
        _confirm(qc, mine)
        stranger = OrgContext(uuid4(), uuid4(), Role.ADMIN)
        assert (
            MatchRepo(qc.session, stranger).release_stale_confirmed({mine.boq_item_id}, set()) == 0
        )
        qc.session.expire_all()
        assert qc.session.get(MatchSuggestion, mine.id).status == "confirmed"
        assert MatchRepo(qc.session, qc.ctx).release_stale_confirmed({mine.boq_item_id}, set()) == 1
