"""Tender data access (tenant-scoped)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import desc, func, select

from app.db.scoped import ScopedRepository
from app.kernel import NotFound

from .models import Tender


class TenderRepo(ScopedRepository[Tender]):
    model = Tender

    def list_for_org(self, include_archived: bool = False) -> Sequence[Tender]:
        where = [] if include_archived else [Tender.status != "archived"]
        return self.find(*where, order_by=desc(Tender.created_at))

    def get_fresh(self, tender_id: UUID) -> Tender:
        """The tender re-read from the database: call after taking the tender lock, when a
        concurrent archive may have committed since an earlier read."""
        row = self.session.scalar(
            self._select().where(Tender.id == tender_id).execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFound("Tender not found")
        return row

    def count_active(self) -> int:
        return (
            self.session.scalar(
                select(func.count(Tender.id)).where(
                    Tender.organisation_id == self.ctx.organisation_id, Tender.status != "archived"
                )
            )
            or 0
        )
