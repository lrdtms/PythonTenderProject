"""Plan, limits and current usage (mocked billing: no payment exists)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.api.limits import gather_counts
from app.modules.billing import public as billing

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


@router.get("", response_model=billing.UsageDTO)
def get_usage(ctx: Ctx, session: DbSession):
    return billing.usage_for(session, ctx, gather_counts(session, ctx))


@router.put("/plan", response_model=billing.UsageDTO)
def switch_plan(body: billing.PlanChange, ctx: Ctx, session: DbSession):
    return billing.set_plan(session, ctx, body.plan_code, gather_counts(session, ctx))
