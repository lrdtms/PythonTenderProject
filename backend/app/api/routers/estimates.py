"""Estimates: pricing defaults (Slice 5b)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.kernel import NotFound
from app.modules.estimates import public as estimates

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
