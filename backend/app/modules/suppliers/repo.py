"""Supplier, quotation and quotation item data access (tenant-scoped)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.db.scoped import ScopedRepository
from app.kernel import Conflict

from .models import MatchSuggestion, Quotation, QuotationItem, Supplier


class SupplierRepo(ScopedRepository[Supplier]):
    model = Supplier

    def by_key(self, name_key: str) -> Supplier | None:
        return self.session.scalar(self._select().where(Supplier.name_key == name_key))

    def get_or_create(self, name: str, name_key: str) -> tuple[Supplier, bool]:
        """Race-safe: a concurrent creator of the same key makes this call return its row. If the
        twin that blocked the insert is deleted (a merge) before we read it, try once more."""
        for _ in range(2):
            stmt = (
                pg_insert(Supplier)
                .values(organisation_id=self.ctx.organisation_id, name=name, name_key=name_key)
                .on_conflict_do_nothing(index_elements=["organisation_id", "name_key"])
                .returning(Supplier.id)
            )
            inserted = self.session.execute(stmt).scalar_one_or_none()
            supplier = self.by_key(name_key)
            if supplier is not None:
                return supplier, inserted is not None
        raise Conflict("The suppliers changed. Try again.", code="try_again")

    def list_with_counts(self) -> list[tuple[Supplier, int]]:
        count = func.count(Quotation.id)
        stmt = (
            select(Supplier, count)
            .outerjoin(
                Quotation,
                (Quotation.organisation_id == Supplier.organisation_id)
                & (Quotation.supplier_id == Supplier.id),
            )
            .where(Supplier.organisation_id == self.ctx.organisation_id)
            .group_by(Supplier.id)
            .order_by(func.lower(Supplier.name), Supplier.id)
        )
        return [(s, int(n)) for s, n in self.session.execute(stmt).all()]

    def quotation_count(self, supplier_id: UUID) -> int:
        stmt = select(func.count(Quotation.id)).where(
            Quotation.organisation_id == self.ctx.organisation_id,
            Quotation.supplier_id == supplier_id,
        )
        return int(self.session.scalar(stmt) or 0)

    def rename(self, supplier: Supplier, name: str, key: str) -> Supplier:
        clash = self.session.scalar(
            select(Supplier.id).where(
                Supplier.organisation_id == self.ctx.organisation_id,
                Supplier.name_key == key,
                Supplier.id != supplier.id,
            )
        )
        exists = Conflict("A supplier with this name already exists.", code="supplier_exists")
        if clash is not None:
            raise exists
        try:  # a concurrent rename or create can still win the unique index
            with self.session.begin_nested():
                supplier.name, supplier.name_key = name, key
                self.session.flush()
        except IntegrityError:
            raise exists from None
        return supplier

    def version_ids(self, supplier_id: UUID) -> set[UUID]:
        stmt = select(Quotation.document_version_id).where(
            Quotation.organisation_id == self.ctx.organisation_id,
            Quotation.supplier_id == supplier_id,
        )
        return set(self.session.scalars(stmt))

    def confirmed_boq_ids(self, supplier_id: UUID) -> set[UUID]:
        stmt = select(MatchSuggestion.boq_item_id).where(
            MatchSuggestion.organisation_id == self.ctx.organisation_id,
            MatchSuggestion.supplier_id == supplier_id,
            MatchSuggestion.status == "confirmed",
        )
        return set(self.session.scalars(stmt))

    def move_to(self, source_id: UUID, target_id: UUID) -> None:
        """Re-point the source supplier's quotations and matches at the target."""
        org = self.ctx.organisation_id
        self.session.execute(
            update(Quotation)
            .where(Quotation.organisation_id == org, Quotation.supplier_id == source_id)
            .values(supplier_id=target_id)
        )
        self.session.execute(
            update(MatchSuggestion)
            .where(MatchSuggestion.organisation_id == org, MatchSuggestion.supplier_id == source_id)
            .values(supplier_id=target_id)
        )

    def remove(self, supplier: Supplier) -> None:
        self.session.delete(supplier)
        self.session.flush()


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
