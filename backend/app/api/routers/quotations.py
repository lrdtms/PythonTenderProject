"""Quotations and their items: list, header edit, item review (Slice 5a).

Writes refuse an archived tender (409 `tender_archived`) and take the tender lock, then (for items)
the extraction lock of the version, in the same order the extraction handlers use. An item edit or
rejection changes what matching sees, so it queues the tender's matching job."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import Ctx, DbSession
from app.api.matching_trigger import enqueue_match
from app.api.reviewers import with_reviewer_names
from app.api.tender_guard import refuse_archived
from app.modules.documents import public as documents
from app.modules.pipeline import public as pipeline
from app.modules.suppliers import public as suppliers

router = APIRouter(prefix="/api/v1", tags=["quotations"])


def _lock_writable_tender(session, ctx, version_id: UUID) -> UUID:
    """Refuse an archived tender, then take its lock. Returns the tender id."""
    info = documents.processing_info(session, ctx, version_id)
    if info.tender_archived:
        refuse_archived(session, ctx, info.tender_id)
    suppliers.lock_tender(session, ctx, info.tender_id)
    refuse_archived(session, ctx, info.tender_id, fresh=True)  # re-check once the lock is ours
    return info.tender_id


@router.get("/tenders/{tender_id}/quotations", response_model=list[suppliers.QuotationDTO])
def tender_quotations(tender_id: UUID, ctx: Ctx, session: DbSession):
    """Quotations of the current version of each quotation document in this tender."""
    docs = documents.list_documents(session, ctx, tender_id)  # NotFound for another organisation
    version_ids = [
        d.current_version.id for d in docs if d.kind == "quotation" and d.current_version
    ]
    return suppliers.list_quotations(session, ctx, version_ids)


@router.patch("/quotations/{quotation_id}", response_model=suppliers.QuotationDTO)
def update_quotation(
    quotation_id: UUID, body: suppliers.QuotationPatch, ctx: Ctx, session: DbSession
):
    version_id = suppliers.get_quotation_tender_version(session, ctx, quotation_id)
    tender_id = _lock_writable_tender(session, ctx, version_id)
    dto = suppliers.update_quotation(session, ctx, quotation_id, body)
    if "supplier_id" in body.model_fields_set:  # a switch moves matches: matching must run again
        enqueue_match(session, ctx, tender_id)
    return dto


@router.get(
    "/document-versions/{version_id}/quotation-items",
    response_model=list[suppliers.QuotationItemDTO],
)
def version_quotation_items(
    version_id: UUID,
    ctx: Ctx,
    session: DbSession,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    documents.get_version(session, ctx, version_id)  # NotFound for another organisation
    rows = suppliers.list_quotation_items(session, ctx, version_id, limit, offset)
    return with_reviewer_names(session, ctx, rows)


def _review(session, ctx, item_id: UUID, action, patch=None, rematch: bool = False):
    version_id = suppliers.quotation_item_version(session, ctx, item_id)
    tender_id = _lock_writable_tender(session, ctx, version_id)
    pipeline.lock_runs(session, ctx, version_id, "quotation")
    dto = suppliers.review_quotation_item(session, ctx, item_id, action, patch)
    if rematch:
        enqueue_match(session, ctx, tender_id)
    return with_reviewer_names(session, ctx, [dto])[0]


@router.patch("/quotation-items/{quotation_item_id}", response_model=suppliers.QuotationItemDTO)
def correct_quotation_item(
    quotation_item_id: UUID, body: suppliers.QuotationItemPatch, ctx: Ctx, session: DbSession
):
    return _review(session, ctx, quotation_item_id, "correct", body, rematch=True)


@router.post(
    "/quotation-items/{quotation_item_id}/confirm", response_model=suppliers.QuotationItemDTO
)
def confirm_quotation_item(quotation_item_id: UUID, ctx: Ctx, session: DbSession):
    return _review(session, ctx, quotation_item_id, "confirm")


@router.post(
    "/quotation-items/{quotation_item_id}/reject", response_model=suppliers.QuotationItemDTO
)
def reject_quotation_item(quotation_item_id: UUID, ctx: Ctx, session: DbSession):
    return _review(session, ctx, quotation_item_id, "reject", rematch=True)
