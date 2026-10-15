"""Extraction: trigger a run and read its results."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import Ctx, DbSession
from app.modules.checklist import public as checklist
from app.modules.documents import public as documents
from app.modules.estimating import public as estimating
from app.modules.jobs import public as jobs
from app.modules.pipeline import public as pipeline

router = APIRouter(prefix="/api/v1/document-versions", tags=["extraction"])


class ExtractRequest(BaseModel):
    deep_scan: bool = False


@router.post("/{version_id}/extract", response_model=list[jobs.JobDTO], status_code=202)
def extract(version_id: UUID, body: ExtractRequest, ctx: Ctx, session: DbSession):
    return pipeline.request_extraction(session, ctx, version_id, body.deep_scan)


@router.get("/{version_id}/extraction", response_model=pipeline.ExtractionStatusDTO)
def extraction_status(version_id: UUID, ctx: Ctx, session: DbSession):
    return pipeline.extraction_status(session, ctx, version_id)


@router.get("/{version_id}/boq-items", response_model=list[estimating.BoqItemDTO])
def boq_items(
    version_id: UUID,
    ctx: Ctx,
    session: DbSession,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    documents.get_version(session, ctx, version_id)  # NotFound for another organisation
    return estimating.list_boq_items(session, ctx, version_id, limit, offset)


@router.get("/{version_id}/requirements", response_model=list[checklist.RequirementDTO])
def requirements(
    version_id: UUID,
    ctx: Ctx,
    session: DbSession,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    documents.get_version(session, ctx, version_id)  # NotFound for another organisation
    return checklist.list_requirements(session, ctx, version_id, limit, offset)
