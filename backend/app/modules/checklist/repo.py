"""Requirement data access (tenant-scoped)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select

from app.db.scoped import ScopedRepository
from app.kernel import NotFound

from .models import Requirement


class RequirementRepo(ScopedRepository[Requirement]):
    model = Requirement

    def for_version(self, version_id: UUID, limit: int, offset: int) -> Sequence[Requirement]:
        stmt = (
            self._select()
            .where(Requirement.document_version_id == version_id)
            .order_by(Requirement.source_order, Requirement.position, Requirement.id)
            .limit(limit)
            .offset(offset)
        )
        return self.session.scalars(stmt).all()

    def for_versions(
        self,
        version_ids: Sequence[UUID],
        review_status: str | None,
        requirement_type: str | None,
        limit: int,
        offset: int,
    ) -> Sequence[Requirement]:
        stmt = self._select().where(Requirement.document_version_id.in_(version_ids))
        if review_status:
            stmt = stmt.where(Requirement.review_status == review_status)
        if requirement_type:
            stmt = stmt.where(Requirement.requirement_type == requirement_type)
        stmt = (
            stmt.order_by(Requirement.source_order, Requirement.position, Requirement.id)
            .limit(limit)
            .offset(offset)
        )
        return self.session.scalars(stmt).all()

    def reviewed(self, version_id: UUID) -> Sequence[Requirement]:
        return self.find(
            Requirement.document_version_id == version_id,
            Requirement.review_status != "unreviewed",
        )

    def delete_unreviewed(self, version_id: UUID) -> None:
        self.session.execute(
            self._delete().where(
                Requirement.document_version_id == version_id,
                Requirement.review_status == "unreviewed",
            )
        )

    def insert_many(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if rows:
            owner = {"organisation_id": self.ctx.organisation_id}
            self.session.execute(insert(Requirement), [{**r, **owner} for r in rows])

    def version_id_of(self, item_id: UUID) -> UUID:
        version_id = self.session.scalar(
            select(Requirement.document_version_id).where(
                Requirement.organisation_id == self.ctx.organisation_id, Requirement.id == item_id
            )
        )
        if version_id is None:
            raise NotFound("Requirement not found")
        return version_id

    def fresh(self, item_id: UUID) -> Requirement | None:
        """Re-read the row after taking the extraction lock; None when a re-run deleted it."""
        return self.session.scalar(
            self._select()
            .where(Requirement.id == item_id)
            .execution_options(populate_existing=True)
        )
