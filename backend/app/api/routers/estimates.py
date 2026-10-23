"""Estimates: pricing defaults, create, and read (Slice 5b).

The router does the orchestration the `estimates` module may not: it takes the tender lock, then
reads the tender's current BoQ lines and confirmed matches through the other modules' public
APIs and maps them to the plain inputs the estimates module works on."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api import estimate_inputs
from app.api.deps import Ctx, DbSession
from app.api.reviewers import with_estimate_names
from app.api.tender_guard import refuse_archived
from app.kernel import NotFound, Permission
from app.modules.estimates import public as estimates
from app.modules.suppliers import public as suppliers
from app.modules.tenders import public as tenders

router = APIRouter(prefix="/api/v1", tags=["estimates"])


@router.get("/pricing-defaults", response_model=estimates.PricingDefaultsDTO)
def get_pricing_defaults(ctx: Ctx, session: DbSession):
    dto = estimates.get_defaults(session, ctx)
    if dto is None:
        raise NotFound("Pricing defaults have not been set.", code="pricing_defaults_missing")
    return dto


@router.put("/pricing-defaults", response_model=estimates.PricingDefaultsDTO)
def put_pricing_defaults(body: estimates.PricingDefaultsPut, ctx: Ctx, session: DbSession):
    return estimates.save_defaults(session, ctx, body)


@router.get("/tenders/{tender_id}/estimates", response_model=list[estimates.EstimateSummaryDTO])
def list_estimates(tender_id: UUID, ctx: Ctx, session: DbSession):
    tenders.get_tender(session, ctx, tender_id)  # NotFound for another organisation
    return estimates.list_estimates(session, ctx, tender_id)


@router.post(
    "/tenders/{tender_id}/estimates", response_model=estimates.EstimateDTO, status_code=201
)
def create_estimate(tender_id: UUID, ctx: Ctx, session: DbSession):
    tenders.get_tender(session, ctx, tender_id)  # NotFound for another organisation
    ctx.require(Permission.REVIEW_DATA)
    refuse_archived(session, ctx, tender_id)
    suppliers.lock_tender(session, ctx, tender_id)
    refuse_archived(session, ctx, tender_id, fresh=True)  # an archive may have committed meanwhile
    boq, _ = estimate_inputs.current_boq(session, ctx, tender_id)
    dto = estimates.create_estimate(session, ctx, tender_id, estimate_inputs.boq_inputs(boq))
    return with_estimate_names(session, ctx, dto)


@router.get("/estimates/{estimate_id}", response_model=estimates.EstimateDTO)
def get_estimate(estimate_id: UUID, ctx: Ctx, session: DbSession):
    tender_id = estimates.tender_of(session, ctx, estimate_id)
    dto = estimates.get_estimate(
        session, ctx, estimate_id, estimate_inputs.live_inputs(session, ctx, tender_id)
    )
    return with_estimate_names(session, ctx, dto)


@router.get("/estimates/{estimate_id}/lines", response_model=list[estimates.EstimateLineDTO])
def get_lines(
    estimate_id: UUID,
    ctx: Ctx,
    session: DbSession,
    status: Literal["priced", "excluded", "unresolved", "changed"] | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    tender_id = estimates.tender_of(session, ctx, estimate_id)
    live = estimate_inputs.live_inputs(session, ctx, tender_id)
    return estimates.list_lines(session, ctx, estimate_id, live, status, limit, offset)


def _locked_live(
    session, ctx, tender_id: UUID, permission: Permission = Permission.REVIEW_DATA
) -> estimates.LiveInputs:
    """Authorise, refuse an archived tender, take the tender lock, then read the live inputs.
    The estimate row lock is taken afterwards, in the service."""
    ctx.require(permission)
    refuse_archived(session, ctx, tender_id)
    suppliers.lock_tender(session, ctx, tender_id)
    refuse_archived(session, ctx, tender_id, fresh=True)  # an archive may have committed meanwhile
    return estimate_inputs.live_inputs(session, ctx, tender_id)


@router.patch("/estimates/{estimate_id}", response_model=estimates.EstimateDTO)
def patch_estimate(estimate_id: UUID, body: estimates.EstimatePatch, ctx: Ctx, session: DbSession):
    tender_id = estimates.tender_of(session, ctx, estimate_id)
    live = _locked_live(session, ctx, tender_id)
    dto = estimates.patch_estimate(session, ctx, estimate_id, body, live)
    return with_estimate_names(session, ctx, dto)


@router.put("/estimate-lines/{line_id}", response_model=estimates.EstimateLineDTO)
def put_line(line_id: UUID, body: estimates.LinePut, ctx: Ctx, session: DbSession):
    tender_id = estimates.line_tender(session, ctx, line_id)
    live = _locked_live(session, ctx, tender_id)
    return estimates.price_line(session, ctx, line_id, body, live)


@router.post("/estimate-lines/{line_id}/refresh", response_model=estimates.EstimateLineDTO)
def refresh_line(line_id: UUID, ctx: Ctx, session: DbSession):
    tender_id = estimates.line_tender(session, ctx, line_id)
    live = _locked_live(session, ctx, tender_id)
    return estimates.refresh_line(session, ctx, line_id, live)


@router.post("/estimates/{estimate_id}/review", response_model=estimates.EstimateDTO)
def review_estimate(estimate_id: UUID, ctx: Ctx, session: DbSession):
    tender_id = estimates.tender_of(session, ctx, estimate_id)
    live = _locked_live(session, ctx, tender_id)
    dto = estimates.review_estimate(session, ctx, estimate_id, live)
    return with_estimate_names(session, ctx, dto)


@router.post("/estimates/{estimate_id}/reopen", response_model=estimates.EstimateDTO)
def reopen_estimate(estimate_id: UUID, ctx: Ctx, session: DbSession):
    tender_id = estimates.tender_of(session, ctx, estimate_id)
    live = _locked_live(session, ctx, tender_id)
    dto = estimates.reopen_estimate(session, ctx, estimate_id, live)
    return with_estimate_names(session, ctx, dto)


@router.post("/estimates/{estimate_id}/approve", response_model=estimates.EstimateDTO)
def approve_estimate(estimate_id: UUID, ctx: Ctx, session: DbSession):
    tender_id = estimates.tender_of(session, ctx, estimate_id)
    live = _locked_live(session, ctx, tender_id, Permission.APPROVE_ESTIMATE)
    dto = estimates.approve_estimate(session, ctx, estimate_id, live)
    return with_estimate_names(session, ctx, dto)
