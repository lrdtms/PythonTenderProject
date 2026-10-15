"""Tender data access (tenant-scoped)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import desc

from app.db.scoped import ScopedRepository

from .models import Tender


class TenderRepo(ScopedRepository[Tender]):
    model = Tender

    def list_for_org(self, include_archived: bool = False) -> Sequence[Tender]:
        where = [] if include_archived else [Tender.status != "archived"]
        return self.find(*where, order_by=desc(Tender.created_at))
