"""Review writes: confirm, correct or reject extracted rows (Slice 4).

Each write looks the row up (404 if unknown or foreign), refuses an archived tender (409
`tender_archived`), takes the same lock extraction takes for that version and kind, then lets
the owning module re-read and write (409 `row_replaced` if a re-run deleted the row in between)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import Ctx, DbSession
from app.api.matching_trigger import enqueue_match
from app.api.reviewers import with_reviewer_names
from app.kernel import Conflict
from app.kernel.vocab import REQUIREMENT_TYPES
from app.modules.checklist import public as checklist
from app.modules.documents import public as documents
from app.modules.estimating import public as estimating
from app.modules.pipeline import public as pipeline

router = APIRouter(prefix="/api/v1", tags=["review"])


def _writable(session, ctx, version_id: UUID) -> None:
    """An archived tender is read-only: refuse before taking the lock."""
    if documents.processing_info(session, ctx, version_id).tender_archived:
        raise Conflict(
            "This tender is archived. Re-open it before reviewing.", code="tender_archived"
        )


def _boq(session, ctx, item_id: UUID, action, patch=None):
    version_id = estimating.version_of(session, ctx, item_id)
    _writable(session, ctx, version_id)
    pipeline.lock_runs(session, ctx, version_id, "boq")
    dto = estimating.review_item(session, ctx, item_id, action, patch)
    if action in ("correct", "reject"):  # matching reads the BoQ text and skips rejected lines
        enqueue_match(session, ctx, documents.processing_info(session, ctx, version_id).tender_id)
    return with_reviewer_names(session, ctx, [dto])[0]


@router.patch("/boq-items/{boq_item_id}", response_model=estimating.BoqItemDTO)
def correct_boq_item(boq_item_id: UUID, body: estimating.BoqPatch, ctx: Ctx, session: DbSession):
    return _boq(session, ctx, boq_item_id, "correct", body)


@router.post("/boq-items/{boq_item_id}/confirm", response_model=estimating.BoqItemDTO)
def confirm_boq_item(boq_item_id: UUID, ctx: Ctx, session: DbSession):
    return _boq(session, ctx, boq_item_id, "confirm")


@router.post("/boq-items/{boq_item_id}/reject", response_model=estimating.BoqItemDTO)
def reject_boq_item(boq_item_id: UUID, ctx: Ctx, session: DbSession):
    return _boq(session, ctx, boq_item_id, "reject")


def _requirement(session, ctx, row_id: UUID, action, patch=None):
    version_id = checklist.version_of(session, ctx, row_id)
    _writable(session, ctx, version_id)
    pipeline.lock_runs(session, ctx, version_id, "requirements")
    dto = checklist.review_item(session, ctx, row_id, action, patch)
    return with_reviewer_names(session, ctx, [dto])[0]


@router.patch("/requirements/{requirement_id}", response_model=checklist.RequirementDTO)
def correct_requirement(
    requirement_id: UUID, body: checklist.RequirementPatch, ctx: Ctx, session: DbSession
):
    return _requirement(session, ctx, requirement_id, "correct", body)


@router.post("/requirements/{requirement_id}/confirm", response_model=checklist.RequirementDTO)
def confirm_requirement(requirement_id: UUID, ctx: Ctx, session: DbSession):
    return _requirement(session, ctx, requirement_id, "confirm")


@router.post("/requirements/{requirement_id}/reject", response_model=checklist.RequirementDTO)
def reject_requirement(requirement_id: UUID, ctx: Ctx, session: DbSession):
    return _requirement(session, ctx, requirement_id, "reject")


@router.get("/tenders/{tender_id}/requirements", response_model=list[checklist.RequirementDTO])
def tender_requirements(
    tender_id: UUID,
    ctx: Ctx,
    session: DbSession,
    review_status: Literal["unreviewed", "confirmed", "corrected", "rejected"] | None = None,
    requirement_type: Literal[*REQUIREMENT_TYPES] | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """The checklist: requirements of every document's current version in this tender."""
    docs = documents.list_documents(session, ctx, tender_id)  # NotFound for another organisation
    version_ids = [d.current_version.id for d in docs if d.current_version]
    rows = checklist.list_for_versions(
        session, ctx, version_ids, review_status, requirement_type, limit, offset
    )
    return with_reviewer_names(session, ctx, rows)
