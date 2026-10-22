"""Estimate, estimate line and pricing default data access (tenant-scoped)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.scoped import ScopedRepository
from app.kernel import NotFound

from .models import Estimate, EstimateLine, PricingDefaults


class EstimateRepo(ScopedRepository[Estimate]):
    model = Estimate

    def get_for_update(self, estimate_id: UUID) -> Estimate:
        """The estimate, row-locked and re-read; NotFound across organisations."""
        row = self.session.scalar(
            self._select()
            .where(Estimate.id == estimate_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFound("Estimate not found")
        return row

    def latest_version(self, tender_id: UUID) -> int:
        stmt = select(func.max(Estimate.version)).where(
            Estimate.organisation_id == self.ctx.organisation_id, Estimate.tender_id == tender_id
        )
        return int(self.session.scalar(stmt) or 0)

    def draft_for(self, tender_id: UUID) -> Estimate | None:
        return self.session.scalar(
            self._select().where(Estimate.tender_id == tender_id, Estimate.status == "draft")
        )

    def lines(
        self, estimate_id: UUID, limit: int, offset: int, status: str | None = None
    ) -> Sequence[EstimateLine]:
        """Lines in BoQ order; `status` filters on `price_source`."""
        stmt = select(EstimateLine).where(
            EstimateLine.organisation_id == self.ctx.organisation_id,
            EstimateLine.estimate_id == estimate_id,
        )
        if status is not None:
            stmt = stmt.where(EstimateLine.price_source == status)
        stmt = stmt.order_by(EstimateLine.position, EstimateLine.id).limit(limit).offset(offset)
        return self.session.scalars(stmt).all()

    def add_lines(self, rows: Sequence[EstimateLine]) -> None:
        for row in rows:
            row.organisation_id = self.ctx.organisation_id
        self.session.add_all(rows)
        self.session.flush()

    def defaults(self) -> PricingDefaults | None:
        return self.session.scalar(
            select(PricingDefaults).where(
                PricingDefaults.organisation_id == self.ctx.organisation_id
            )
        )

    def save_defaults(
        self,
        currency: str,
        vat_rate: Decimal,
        markup_basis: str,
        default_markup_percent: Decimal,
        updated_by: UUID,
    ) -> PricingDefaults:
        values = {
            "currency": currency,
            "vat_rate": vat_rate,
            "markup_basis": markup_basis,
            "default_markup_percent": default_markup_percent,
            "updated_by": updated_by,
            "updated_at": func.now(),
        }
        self.session.execute(
            pg_insert(PricingDefaults)
            .values(organisation_id=self.ctx.organisation_id, **values)
            .on_conflict_do_update(index_elements=["organisation_id"], set_=values)
        )
        saved = self.session.scalar(
            select(PricingDefaults)
            .where(PricingDefaults.organisation_id == self.ctx.organisation_id)
            .execution_options(populate_existing=True)
        )
        if saved is None:  # cannot happen right after the upsert
            raise NotFound("Pricing defaults not found")
        return saved
