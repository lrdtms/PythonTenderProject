"""Tender workspaces."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.modules.tenders import public as tenders

router = APIRouter(prefix="/api/v1/tenders", tags=["tenders"])


@router.post("", response_model=tenders.TenderDTO, status_code=201)
def create_tender(body: tenders.TenderCreate, ctx: Ctx, session: DbSession):
    return tenders.create_tender(session, ctx, body)


@router.get("", response_model=list[tenders.TenderDTO])
def list_tenders(ctx: Ctx, session: DbSession, include_archived: bool = False):
    return tenders.list_tenders(session, ctx, include_archived)


@router.get("/{tender_id}", response_model=tenders.TenderDTO)
def get_tender(tender_id: UUID, ctx: Ctx, session: DbSession):
    return tenders.get_tender(session, ctx, tender_id)


@router.patch("/{tender_id}", response_model=tenders.TenderDTO)
def update_tender(tender_id: UUID, body: tenders.TenderUpdate, ctx: Ctx, session: DbSession):
    return tenders.update_tender(session, ctx, tender_id, body)


@router.post("/{tender_id}/archive", response_model=tenders.TenderDTO)
def archive_tender(tender_id: UUID, ctx: Ctx, session: DbSession):
    return tenders.archive_tender(session, ctx, tender_id)
