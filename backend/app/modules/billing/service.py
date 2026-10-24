"""Plan limits (mocked billing). Counts are supplied by the caller, who reads them from the
owning modules, so this module never touches another module's tables."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from app.kernel import LimitExceeded, NotFound, OrgContext, Permission
from app.modules.audit import public as audit

from .models import Plan
from .repo import BillingRepo
from .schemas import PlanOption, UsageDTO, UsageItem

BYTES_PER_MB = 1024 * 1024


class Resource(StrEnum):
    TENDERS = "tenders"
    UPLOADS = "uploads"
    STORAGE_MB = "storage_mb"
    EXPORTS = "exports"
    MEMBERS = "members"


LABELS = {
    Resource.TENDERS: "Active tenders",
    Resource.UPLOADS: "Uploads this month",
    Resource.STORAGE_MB: "Storage",
    Resource.EXPORTS: "Exports this month",
    Resource.MEMBERS: "Members",
}
PERIODS = {
    Resource.TENDERS: "current",
    Resource.UPLOADS: "month",
    Resource.STORAGE_MB: "current",
    Resource.EXPORTS: "month",
    Resource.MEMBERS: "current",
}


@dataclass(frozen=True)
class Counts:
    tenders: int
    uploads: int
    storage_bytes: int
    exports: int
    members: int


def month_start(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def _limit(plan: Plan, resource: Resource) -> int:
    return {
        Resource.TENDERS: plan.max_tenders,
        Resource.UPLOADS: plan.max_uploads_per_month,
        Resource.STORAGE_MB: plan.max_storage_mb,
        Resource.EXPORTS: plan.max_exports_per_month,
        Resource.MEMBERS: plan.max_members,
    }[resource]


def _mb_up(n_bytes: int) -> int:
    return -(-n_bytes // BYTES_PER_MB)


def usage_for(session: Session, ctx: OrgContext, counts: Counts) -> UsageDTO:
    ctx.require(Permission.READ)
    repo = BillingRepo(session, ctx)
    plan = repo.current_plan()
    used = {
        Resource.TENDERS: counts.tenders,
        Resource.UPLOADS: counts.uploads,
        Resource.STORAGE_MB: _mb_up(counts.storage_bytes),
        Resource.EXPORTS: counts.exports,
        Resource.MEMBERS: counts.members,
    }
    return UsageDTO(
        plan_code=plan.code,
        plan_name=plan.name,
        items=[
            UsageItem(
                resource=r.value,
                label=LABELS[r],
                used=used[r],
                limit=_limit(plan, r),
                period=PERIODS[r],  # type: ignore[arg-type]
            )
            for r in Resource
        ],
        available_plans=[PlanOption(code=p.code, name=p.name) for p in repo.plans()],
    )


def check_limit(
    session: Session,
    ctx: OrgContext,
    resource: Resource,
    count: Callable[[], int],
    adding: int = 1,
) -> None:
    """Refuse when `count() + adding` would pass the plan limit. Takes the per-organisation
    resource lock first, so the count and the caller's insert (same transaction) cannot race.
    Storage counts and `adding` are in bytes."""
    repo = BillingRepo(session, ctx)
    repo.lock(resource.value)
    plan = repo.current_plan()
    limit = _limit(plan, resource)
    used = count()
    if resource is Resource.STORAGE_MB:
        if used + adding > limit * BYTES_PER_MB:
            raise LimitExceeded(
                f"Storage limit reached on the {plan.name} plan "
                f"({_mb_up(used)} of {limit} MB used)."
            )
        return
    if used + adding > limit:
        raise LimitExceeded(
            f"{LABELS[resource]} limit reached on the {plan.name} plan ({used} of {limit})."
        )


def set_plan(session: Session, ctx: OrgContext, plan_code: str, counts: Counts) -> UsageDTO:
    ctx.require(Permission.MANAGE_MEMBERS)
    repo = BillingRepo(session, ctx)
    if repo.plan(plan_code) is None:
        raise NotFound("Plan not found")
    old = repo.chosen_code()
    repo.choose(plan_code)
    audit.record(
        session,
        ctx,
        "organisation",
        ctx.organisation_id,
        "plan_changed",
        {"old_status": old, "new_status": plan_code},
    )
    return usage_for(session, ctx, counts)
