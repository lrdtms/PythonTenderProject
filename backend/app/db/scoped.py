"""The one tenant-scoped data-access path (ADR-0005).

Every repository for organisation-owned data extends `ScopedRepository`. It adds
`organisation_id = ctx.organisation_id` to every query and stamps it on every insert.
A row of another organisation is reported as NotFound (never Forbidden).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.kernel import NotFound, OrgContext


class ScopedRepository[M]:
    model: ClassVar[type[Any]]

    def __init__(self, session: Session, ctx: OrgContext):
        if not hasattr(self.model, "organisation_id"):
            raise TypeError(f"{self.model.__name__} has no organisation_id; use a plain repository")
        self.session = session
        self.ctx = ctx

    def _select(self) -> Select[Any]:
        return select(self.model).where(self.model.organisation_id == self.ctx.organisation_id)

    def get(self, entity_id: UUID) -> M:
        row = self.session.scalar(self._select().where(self.model.id == entity_id))
        if row is None:
            raise NotFound(f"{self.model.__name__} not found")
        return row

    def find(self, *where: Any, order_by: Any = None, limit: int | None = None) -> Sequence[M]:
        stmt = self._select().where(*where)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        if limit is not None:
            stmt = stmt.limit(limit)
        return self.session.scalars(stmt).all()

    def add(self, entity: M) -> M:
        entity.organisation_id = self.ctx.organisation_id  # type: ignore[attr-defined]
        self.session.add(entity)
        self.session.flush()
        return entity
