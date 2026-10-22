"""Estimate use cases. Pricing defaults first."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.kernel import OrgContext, Permission
from app.modules.audit import public as audit

from .models import PricingDefaults
from .repo import EstimateRepo
from .schemas import PricingDefaultsDTO, PricingDefaultsPut


def _defaults_dto(row: PricingDefaults) -> PricingDefaultsDTO:
    return PricingDefaultsDTO(
        currency=row.currency,
        vat_rate=str(row.vat_rate),
        markup_basis=row.markup_basis,  # type: ignore[arg-type]
        default_markup_percent=str(row.default_markup_percent),
        updated_at=row.updated_at,
    )


def get_defaults(session: Session, ctx: OrgContext) -> PricingDefaultsDTO | None:
    ctx.require(Permission.READ)
    row = EstimateRepo(session, ctx).defaults()
    return _defaults_dto(row) if row is not None else None


def save_defaults(
    session: Session, ctx: OrgContext, body: PricingDefaultsPut
) -> PricingDefaultsDTO:
    ctx.require(Permission.MANAGE_PRICING)
    row = EstimateRepo(session, ctx).save_defaults(
        body.currency,
        Decimal(body.vat_rate),
        body.markup_basis,
        Decimal(body.default_markup_percent),
        ctx.user_id,
    )
    audit.record(
        session,
        ctx,
        "pricing_defaults",
        ctx.organisation_id,
        "pricing_defaults_changed",
        {"fields": ["currency", "vat_rate", "markup_basis", "default_markup_percent"]},
    )
    return _defaults_dto(row)
