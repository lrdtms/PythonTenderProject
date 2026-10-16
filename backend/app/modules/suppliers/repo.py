"""Supplier, quotation and quotation item data access (tenant-scoped)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, text

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

    def for_versions(
        self, version_ids: Collection[UUID]
    ) -> Sequence[tuple[QuotationItem, Quotation]]:
        """Matchable items (not rejected) of the given versions, with their quotation."""
        if not version_ids:
            return []
        stmt = (
            select(QuotationItem, Quotation)
            .join(
                Quotation,
                (Quotation.organisation_id == QuotationItem.organisation_id)
                & (Quotation.id == QuotationItem.quotation_id),
            )
            .where(
                QuotationItem.organisation_id == self.ctx.organisation_id,
                QuotationItem.document_version_id.in_(version_ids),
                QuotationItem.review_status != "rejected",
            )
            .order_by(
                QuotationItem.document_version_id,
                QuotationItem.source_order,
                QuotationItem.position,
                QuotationItem.id,
            )
        )
        return [(i, q) for i, q in self.session.execute(stmt).all()]

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


class MatchRepo(ScopedRepository[MatchSuggestion]):
    model = MatchSuggestion

    def lock_tender(self, tender_id: UUID) -> None:
        """Serialise matching and (Phase 3) match decisions for one tender."""
        key = int.from_bytes(tender_id.bytes[:8], "big", signed=True)
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def for_items(
        self, boq_ids: Collection[UUID], quote_item_ids: Collection[UUID]
    ) -> Sequence[MatchSuggestion]:
        """Matches that touch any of the given BoQ lines or quotation items."""
        if not boq_ids and not quote_item_ids:
            return []
        return self.find(
            MatchSuggestion.boq_item_id.in_(boq_ids)
            | MatchSuggestion.quotation_item_id.in_(quote_item_ids)
        )

    def delete_suggested(self, ids: Collection[UUID]) -> int:
        """Delete undecided rows only; a decided match is never removed here."""
        if not ids:
            return 0
        result = self.session.execute(
            self._delete().where(MatchSuggestion.id.in_(ids), MatchSuggestion.status == "suggested")
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def insert_many(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if rows:
            owner = {"organisation_id": self.ctx.organisation_id}
            self.session.execute(insert(MatchSuggestion), [{**r, **owner} for r in rows])

    def decided_boq_item_ids(self) -> set[UUID]:
        stmt = (
            select(MatchSuggestion.boq_item_id)
            .where(
                MatchSuggestion.organisation_id == self.ctx.organisation_id,
                MatchSuggestion.status.in_(("confirmed", "rejected")),
            )
            .distinct()
        )
        return set(self.session.scalars(stmt))
