"""Tender workspace use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import Conflict, OrgContext, Permission, ValidationFailed
from app.modules.audit import public as audit

from .models import TENDER_STATUSES, Tender
from .repo import TenderRepo
from .schemas import TenderCreate, TenderDTO, TenderUpdate


def _dto(t: Tender) -> TenderDTO:
    return TenderDTO.model_validate(t, from_attributes=True)


def create_tender(session: Session, ctx: OrgContext, data: TenderCreate) -> TenderDTO:
    ctx.require(Permission.EDIT_TENDERS)
    tender = TenderRepo(session, ctx).add(Tender(created_by=ctx.user_id, **data.model_dump()))
    audit.record(session, ctx, "tender", tender.id, "created")
    return _dto(tender)


def list_tenders(
    session: Session, ctx: OrgContext, include_archived: bool = False
) -> list[TenderDTO]:
    ctx.require(Permission.READ)
    return [_dto(t) for t in TenderRepo(session, ctx).list_for_org(include_archived)]


def get_tender(session: Session, ctx: OrgContext, tender_id: UUID) -> TenderDTO:
    ctx.require(Permission.READ)
    return _dto(TenderRepo(session, ctx).get(tender_id))


def update_tender(
    session: Session, ctx: OrgContext, tender_id: UUID, data: TenderUpdate
) -> TenderDTO:
    ctx.require(Permission.EDIT_TENDERS)
    tender = TenderRepo(session, ctx).get(tender_id)
    changes = data.model_dump(exclude_unset=True)
    if "title" in changes and not changes["title"]:
        raise ValidationFailed("A tender needs a title.", {"field": "title"})
    status = changes.get("status")
    if status is not None and status not in TENDER_STATUSES:
        raise ValidationFailed(
            f"Status must be one of: {', '.join(TENDER_STATUSES)}.", {"field": "status"}
        )
    if tender.status == "archived" and (
        set(changes) != {"status"} or changes["status"] == "archived"
    ):
        raise Conflict("An archived tender is read-only. Re-open it first.", {"field": "status"})
    old_status = tender.status
    for key, value in changes.items():
        setattr(tender, key, value)
    if status == "archived" and tender.archived_at is None:
        tender.archived_at = datetime.now(UTC)
    if status and status != "archived":
        tender.archived_at = None
    session.flush()
    audit.record(
        session,
        ctx,
        "tender",
        tender.id,
        "updated",
        {"fields": sorted(changes), "old_status": old_status, "new_status": tender.status},
    )
    return _dto(tender)


def archive_tender(session: Session, ctx: OrgContext, tender_id: UUID) -> TenderDTO:
    return update_tender(session, ctx, tender_id, TenderUpdate(status="archived"))
