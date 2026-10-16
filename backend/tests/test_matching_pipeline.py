"""Matching through the real worker."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from app.db.session import session_scope
from app.kernel import OrgContext, Role
from app.modules.estimating.models import BoqItem
from app.modules.jobs import public as jobs
from app.modules.jobs.models import Job
from app.modules.suppliers.models import MatchSuggestion, Quotation, QuotationItem
from app.worker import handlers
from app.worker.runner import process_one
from tests.conftest import make_tender, register, upload
from tests.test_extraction_pipeline import API, drain

PACK = Path(__file__).parent / "fixtures" / "packs" / "pack02"
QUOTES = ("quotation_1_sparkmore_supplies.pdf", "quotation_2_greenvale_cable_and_conduit.xlsx")


def _up(actor, tender_id, name: str, kind: str) -> str:
    body = upload(actor, tender_id, (PACK / name).read_bytes(), name, kind=kind).json()
    drain()
    return body["version"]["id"]


def _full(email: str):
    actor = register(email)
    tender_id = make_tender(actor)
    boq = _up(actor, tender_id, "boq.xlsx", "boq")
    for name in QUOTES:
        _up(actor, tender_id, name, "quotation")
    return actor, tender_id, boq


def _match_jobs(tender_id: str) -> list[Job]:
    with session_scope() as s:
        stmt = select(Job).where(
            Job.job_type == "match_suppliers", Job.subject_id == UUID(tender_id)
        )
        return list(s.scalars(stmt))


def test_matching_runs_after_boq_and_quotations_are_extracted() -> None:
    actor, tender_id, _ = _full("m1@example.com")
    with session_scope() as s:
        rows = list(s.scalars(select(MatchSuggestion)))
        assert {r.classification for r in rows} >= {"clear", "ambiguous"}
        supplier_of = {q.id: q.supplier_id for q in s.scalars(select(Quotation))}
        for r in rows:
            item = s.get(QuotationItem, r.quotation_item_id)
            assert r.supplier_id == supplier_of[item.quotation_id]
    jobs_ = _match_jobs(tender_id)
    assert jobs_ and all(j.status == "succeeded" for j in jobs_)


def test_a_confirmed_match_survives_boq_reextraction() -> None:
    actor, tender_id, boq = _full("m2@example.com")
    with session_scope() as s:
        match = s.scalars(select(MatchSuggestion)).first()
        match_id, boq_item_id = match.id, match.boq_item_id
        match.status, match.decided_at = "confirmed", datetime.now(UTC)
        match.decided_by = UUID(actor.me["user_id"])
        count = s.scalar(select(func.count()).select_from(BoqItem))
    assert actor.client.post(f"{API}/document-versions/{boq}/extract", json={}).status_code == 202
    drain()
    with session_scope() as s:
        assert s.get(BoqItem, boq_item_id) is not None
        assert s.get(MatchSuggestion, match_id).status == "confirmed"
        assert s.scalar(select(func.count()).select_from(BoqItem)) == count
        later = s.scalars(select(Job).where(Job.job_type == "match_suppliers")).all()
        assert later and all(j.status == "succeeded" for j in later)


def test_quotation_reextraction_keeps_a_decided_pair_unsuggested() -> None:
    actor, tender_id, _ = _full("m3@example.com")
    with session_scope() as s:
        match = s.scalars(select(MatchSuggestion)).first()
        match_id, qitem_id, boq_id = match.id, match.quotation_item_id, match.boq_item_id
        version = s.get(QuotationItem, qitem_id).document_version_id
        match.status, match.decided_at = "confirmed", datetime.now(UTC)
        match.decided_by = UUID(actor.me["user_id"])
    assert (
        actor.client.post(f"{API}/document-versions/{version}/extract", json={}).status_code == 202
    )
    drain()
    with session_scope() as s:
        assert s.get(QuotationItem, qitem_id) is not None
        assert s.get(MatchSuggestion, match_id).status == "confirmed"
        pairs = s.execute(
            select(MatchSuggestion.status).where(
                MatchSuggestion.boq_item_id == boq_id,
                MatchSuggestion.quotation_item_id == qitem_id,
            )
        ).all()
        assert pairs == [("confirmed",)]


def test_tenders_with_only_one_side_match_nothing() -> None:
    actor = register("m4@example.com")
    only_boq = make_tender(actor, "only boq")
    _up(actor, only_boq, "boq.xlsx", "boq")
    only_quotes = make_tender(actor, "only quotes")
    _up(actor, only_quotes, QUOTES[1], "quotation")
    for tid in (only_boq, only_quotes):
        found = _match_jobs(tid)
        assert found and all(j.status == "succeeded" for j in found)
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(MatchSuggestion)) == 0


def test_an_archived_tender_fails_matching_and_writes_nothing() -> None:
    actor, tender_id, _ = _full("m5@example.com")
    with session_scope() as s:
        before = s.scalar(select(func.count()).select_from(MatchSuggestion))
    assert actor.client.post(f"{API}/tenders/{tender_id}/archive").status_code < 300
    ctx = OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)
    with session_scope() as s:
        jobs.enqueue(s, ctx, "match_suppliers", "tender", UUID(tender_id), {})
    drain()
    latest = max(_match_jobs(tender_id), key=lambda j: j.created_at)
    assert latest.status == "failed" and latest.error_code == "TENDER_ARCHIVED"
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(MatchSuggestion)) == before


def test_uploads_in_a_burst_queue_one_active_matching_job() -> None:
    actor = register("m6@example.com")
    tender_id = make_tender(actor)
    for name, kind in (("boq.xlsx", "boq"), *((q, "quotation") for q in QUOTES)):
        upload(actor, tender_id, (PACK / name).read_bytes(), name, kind=kind)
    steps = 0
    while process_one(handlers.HANDLERS) and steps < 30:
        steps += 1
        active = [j for j in _match_jobs(tender_id) if j.status in ("queued", "running")]
        assert len(active) <= 1
    assert steps and all(j.status == "succeeded" for j in _match_jobs(tender_id))
