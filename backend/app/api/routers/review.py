"""Review writes: confirm, correct or reject extracted rows (Slice 4).

Each write looks the row up (404 if unknown or foreign), takes the same lock extraction takes
for that version and kind, then lets the owning module re-read and write (409 `row_replaced`
if a re-run deleted the row in between)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.api.reviewers import with_reviewer_names
from app.modules.estimating import public as estimating
from app.modules.pipeline import public as pipeline

router = APIRouter(prefix="/api/v1", tags=["review"])


def _boq(session, ctx, item_id: UUID, action, patch=None):
    version_id = estimating.version_of(session, ctx, item_id)
    pipeline.lock_runs(session, ctx, version_id, "boq")
    dto = estimating.review_item(session, ctx, item_id, action, patch)
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
