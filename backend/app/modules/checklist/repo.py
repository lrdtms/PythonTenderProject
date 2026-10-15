"""Requirement data access (tenant-scoped)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import insert

from app.db.scoped import ScopedRepository

from .models import Requirement


class RequirementRepo(ScopedRepository[Requirement]):
    model = Requirement

    def for_version(self, version_id: UUID, limit: int, offset: int) -> Sequence[Requirement]:
        stmt = (
            self._select()
            .where(Requirement.document_version_id == version_id)
            .order_by(Requirement.created_at, Requirement.position)
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
