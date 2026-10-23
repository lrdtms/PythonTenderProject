"""Audit view (admin and project manager; enforced in the service)."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import Ctx, DbSession
from app.modules.audit import public as audit
from app.modules.identity import public as identity

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


class AuditEventRow(audit.AuditEventDTO):
    user_name: str | None = None


class AuditRows(BaseModel):
    items: list[AuditEventRow]
    next_cursor: str | None


@router.get("", response_model=AuditRows)
def list_audit(
    ctx: Ctx,
    session: DbSession,
    entity_type: Annotated[str | None, Query(max_length=50)] = None,
    action: Annotated[str | None, Query(max_length=50)] = None,
    user_id: UUID | None = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    filters = audit.AuditFilters(
        entity_type=entity_type,
        action=action,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )
    page = audit.list_events(session, ctx, filters, cursor, limit)
    ids = {e.user_id for e in page.items if e.user_id}
    names = identity.member_names(session, ctx, ids) if ids else {}
    rows = [
        AuditEventRow(**e.model_dump(), user_name=names.get(e.user_id) if e.user_id else None)
        for e in page.items
    ]
    return AuditRows(items=rows, next_cursor=page.next_cursor)


@router.get("/facets", response_model=audit.AuditFacets)
def audit_facets(ctx: Ctx, session: DbSession):
    return audit.facets(session, ctx)
