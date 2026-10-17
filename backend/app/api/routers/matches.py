"""Match suggestions: the grouped list, decisions, confirm-clear and re-matching (Slice 5a).

The list has one entry per current BoQ line (rejected lines excluded), each with its suggestions
from current quotation versions. Nothing sorts or filters by price: suggestions come in BoQ order,
then supplier name, then rank. Every decision refuses an archived tender (409 `tender_archived`),
takes the tender lock, then works from the current BoQ lines and quotation versions read after the
lock, so a concurrent re-extraction or merge cannot slip between the check and the write."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import Ctx, DbSession
from app.api.matching_trigger import enqueue_match
from app.api.reviewers import with_decider_names
from app.api.tender_guard import refuse_archived
from app.kernel import Permission
from app.modules.documents import public as documents
from app.modules.estimating import public as estimating
from app.modules.jobs import public as jobs
from app.modules.suppliers import public as suppliers
from app.modules.tenders import public as tenders

router = APIRouter(prefix="/api/v1", tags=["matches"])

PAGE = 1000
_DTO = suppliers.MatchSuggestionDTO


def _current(session, ctx, tender_id: UUID) -> tuple[list[estimating.BoqItemDTO], list[UUID]]:
    """The tender's current, non-rejected BoQ lines in document order, and the current quotation
    versions."""
    boq: list[estimating.BoqItemDTO] = []
    quote_versions: list[UUID] = []
    for d in documents.list_documents(session, ctx, tender_id):  # NotFound for another org
        v = d.current_version
        if v is None:
            continue
        if d.kind == "quotation":
            quote_versions.append(v.id)
        elif d.kind in ("boq", "tender_document"):
            offset = 0
            while True:
                page = estimating.list_boq_items(session, ctx, v.id, PAGE, offset)
                boq += [i for i in page if i.review_status != "rejected"]
                if len(page) < PAGE:
                    break
                offset += PAGE
    return boq, quote_versions


@router.get("/tenders/{tender_id}/match-suggestions", response_model=list[suppliers.MatchLineDTO])
def match_suggestions(
    tender_id: UUID,
    ctx: Ctx,
    session: DbSession,
    status: Literal["suggested", "confirmed", "rejected"] | None = None,
    classification: Literal["clear", "ambiguous"] | None = None,
    supplier_id: UUID | None = None,
    only_with_suggestions: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    boq, quote_versions = _current(session, ctx, tender_id)
    found = suppliers.suggestions_for(
        session, ctx, [i.id for i in boq], quote_versions, status, classification, supplier_id
    )
    by_line: dict[UUID, list[suppliers.MatchSuggestionDTO]] = {}
    for s in found:
        by_line.setdefault(s.boq_item_id, []).append(s)
    lines = [
        suppliers.MatchLineDTO(
            boq=suppliers.MatchBoqRef(
                id=i.id, item_no=i.item_no, section=i.section, description=i.description,
                unit=i.unit, quantity=i.quantity,
            ),
            suggestions=by_line.get(i.id, []),
        )
        for i in boq
        if by_line.get(i.id) or not only_with_suggestions
    ]  # fmt: skip
    page = lines[offset : offset + limit]
    with_decider_names(session, ctx, [s for line in page for s in line.suggestions])
    return page


def _decide(session, ctx, suggestion_id: UUID, action):
    version_id = suppliers.suggestion_tender_version(session, ctx, suggestion_id)
    tender_id = documents.processing_info(session, ctx, version_id).tender_id
    refuse_archived(session, ctx, tender_id)
    suppliers.lock_tender(session, ctx, tender_id)
    refuse_archived(session, ctx, tender_id, fresh=True)  # an archive may have committed meanwhile
    boq, quote_versions = _current(session, ctx, tender_id)
    dto = suppliers.decide(
        session, ctx, suggestion_id, action, set(quote_versions), {i.id for i in boq}, tender_id
    )
    return with_decider_names(session, ctx, [dto])[0]


@router.post(
    "/match-suggestions/{suggestion_id}/confirm", response_model=suppliers.MatchSuggestionDTO
)
def confirm_suggestion(suggestion_id: UUID, ctx: Ctx, session: DbSession):
    return _decide(session, ctx, suggestion_id, "confirm")


@router.post(
    "/match-suggestions/{suggestion_id}/reject", response_model=suppliers.MatchSuggestionDTO
)
def reject_suggestion(suggestion_id: UUID, ctx: Ctx, session: DbSession):
    return _decide(session, ctx, suggestion_id, "reject")


@router.post(
    "/match-suggestions/{suggestion_id}/reset", response_model=suppliers.MatchSuggestionDTO
)
def reset_suggestion(suggestion_id: UUID, ctx: Ctx, session: DbSession):
    return _decide(session, ctx, suggestion_id, "reset")


@router.post(
    "/tenders/{tender_id}/match-suggestions/confirm-clear",
    response_model=suppliers.ConfirmClearResult,
)
def confirm_clear(tender_id: UUID, ctx: Ctx, session: DbSession):
    tenders.get_tender(session, ctx, tender_id)  # NotFound for another organisation
    ctx.require(Permission.REVIEW_DATA)
    refuse_archived(session, ctx, tender_id)
    suppliers.lock_tender(session, ctx, tender_id)
    refuse_archived(session, ctx, tender_id, fresh=True)
    boq, quote_versions = _current(session, ctx, tender_id)
    return suppliers.confirm_clear(
        session,
        ctx,
        tender_id,
        set(quote_versions),
        {i.id for i in boq},
        {i.id: i.reviewed_at for i in boq if i.review_status == "corrected"},
    )


@router.post("/tenders/{tender_id}/match", response_model=jobs.JobDTO, status_code=202)
def match_tender(tender_id: UUID, ctx: Ctx, session: DbSession):
    """Queue the tender's matching job (the active one when one is queued or running)."""
    tenders.get_tender(session, ctx, tender_id)  # NotFound for another organisation
    ctx.require(Permission.REVIEW_DATA)
    refuse_archived(session, ctx, tender_id)
    suppliers.lock_tender(session, ctx, tender_id)
    refuse_archived(session, ctx, tender_id, fresh=True)
    return enqueue_match(session, ctx, tender_id)
