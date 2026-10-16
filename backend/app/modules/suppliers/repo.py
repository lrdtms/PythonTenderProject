"""Supplier, quotation and quotation item data access (tenant-scoped)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select

from app.db.scoped import ScopedRepository

from .models import MatchSuggestion, Quotation, QuotationItem, Supplier


class SupplierRepo(ScopedRepository[Supplier]):
    model = Supplier

    def by_key(self, name_key: str) -> Supplier | None:
        return self.session.scalar(self._select().where(Supplier.name_key == name_key))


class QuotationRepo(ScopedRepository[Quotation]):
    model = Quotation

    def for_version(self, version_id: UUID) -> Quotation | None:
        return self.session.scalar(
            self._select().where(Quotation.document_version_id == version_id)
        )


class QuotationItemRepo(ScopedRepository[QuotationItem]):
    model = QuotationItem

    def for_quotation(self, quotation_id: UUID) -> Sequence[QuotationItem]:
        stmt = (
            self._select()
            .where(QuotationItem.quotation_id == quotation_id)
            .order_by(QuotationItem.source_order, QuotationItem.position, QuotationItem.id)
        )
        return self.session.scalars(stmt).all()

    def reviewed_or_pinned(self, quotation_id: UUID) -> Sequence[QuotationItem]:
        """Items a re-run must keep: reviewed by a person, or tied to a decided match."""
        decided = select(MatchSuggestion.quotation_item_id).where(
            MatchSuggestion.organisation_id == self.ctx.organisation_id,
            MatchSuggestion.status.in_(("confirmed", "rejected")),
        )
        return self.find(
            QuotationItem.quotation_id == quotation_id,
            (QuotationItem.review_status != "unreviewed") | QuotationItem.id.in_(decided),
        )

    def delete_replaceable(self, quotation_id: UUID, keep_ids: Collection[UUID]) -> None:
        stmt = self._delete().where(QuotationItem.quotation_id == quotation_id)
        if keep_ids:
            stmt = stmt.where(QuotationItem.id.not_in(keep_ids))
        self.session.execute(stmt)

    def insert_many(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if rows:
            owner = {"organisation_id": self.ctx.organisation_id}
            self.session.execute(insert(QuotationItem), [{**r, **owner} for r in rows])
