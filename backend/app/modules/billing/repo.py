"""Billing data access. `plans` is global reference data; `organisation_plans` is scoped by hand
because its primary key is the organisation itself."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.kernel import NotFound, OrgContext

from .models import OrganisationPlan, Plan

DEFAULT_PLAN = "demo"


class BillingRepo:
    def __init__(self, session: Session, ctx: OrgContext):
        self.session = session
        self.ctx = ctx

    def plans(self) -> Sequence[Plan]:
        return self.session.scalars(select(Plan).order_by(Plan.max_tenders.desc())).all()

    def plan(self, code: str) -> Plan | None:
        return self.session.get(Plan, code)

    def chosen_code(self) -> str:
        row = self.session.scalar(
            select(OrganisationPlan).where(
                OrganisationPlan.organisation_id == self.ctx.organisation_id
            )
        )
        return row.plan_code if row else DEFAULT_PLAN

    def current_plan(self) -> Plan:
        plan = self.plan(self.chosen_code())
        if plan is None:  # the plan_code FK and the seeded default make this unreachable
            raise NotFound("Plan not found")
        return plan

    def choose(self, code: str) -> None:
        row = self.session.scalar(
            select(OrganisationPlan)
            .where(OrganisationPlan.organisation_id == self.ctx.organisation_id)
            .with_for_update()
        )
        if row is None:
            self.session.add(
                OrganisationPlan(
                    organisation_id=self.ctx.organisation_id,
                    plan_code=code,
                    changed_by=self.ctx.user_id,
                )
            )
        else:
            row.plan_code = code
            row.changed_by = self.ctx.user_id
        self.session.flush()

    def lock(self, resource: str) -> None:
        """Serialise creators of one resource in one organisation until the transaction ends, so
        two requests cannot both take the last slot."""
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"limit:{self.ctx.organisation_id}:{resource}"},
        )
