"""BoQ item data access (tenant-scoped)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select

from app.db.scoped import ScopedRepository
from app.kernel import NotFound

from .models import BoqItem


class BoqRepo(ScopedRepository[BoqItem]):
    model = BoqItem

    def for_version(self, version_id: UUID, limit: int, offset: int) -> Sequence[BoqItem]:
        stmt = (
            self._select()
            .where(BoqItem.document_version_id == version_id)
            .order_by(BoqItem.source_order, BoqItem.position, BoqItem.id)
            .limit(limit)
            .offset(offset)
        )
        return self.session.scalars(stmt).all()

    def reviewed(self, version_id: UUID) -> Sequence[BoqItem]:
        return self.find(
            BoqItem.document_version_id == version_id, BoqItem.review_status != "unreviewed"
        )

    def delete_unreviewed(self, version_id: UUID) -> None:
        self.session.execute(
            self._delete().where(
                BoqItem.document_version_id == version_id, BoqItem.review_status == "unreviewed"
            )
        )

    def insert_many(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if rows:
            owner = {"organisation_id": self.ctx.organisation_id}
            self.session.execute(insert(BoqItem), [{**r, **owner} for r in rows])

    def version_id_of(self, item_id: UUID) -> UUID:
        version_id = self.session.scalar(
            select(BoqItem.document_version_id).where(
                BoqItem.organisation_id == self.ctx.organisation_id, BoqItem.id == item_id
            )
        )
        if version_id is None:
            raise NotFound("BoqItem not found")
        return version_id

    def fresh(self, item_id: UUID) -> BoqItem | None:
        """Re-read the row after taking the extraction lock; None when a re-run deleted it."""
        return self.session.scalar(
            self._select().where(BoqItem.id == item_id).execution_options(populate_existing=True)
        )
