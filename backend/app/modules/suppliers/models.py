"""Suppliers, their quotations and the match suggestions between quotation items and BoQ lines."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

QUOTATION_REVIEW_STATUSES = ("unreviewed", "confirmed", "corrected", "rejected")
MATCH_STATUSES = ("suggested", "confirmed", "rejected")
MATCH_CLASSIFICATIONS = ("clear", "ambiguous")


def _org_col() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("organisations.id"), nullable=False)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = _org_col()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_key: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_suppliers_org_id"),
        UniqueConstraint("organisation_id", "name_key", name="uq_suppliers_org_name_key"),
    )


class Quotation(Base):
    __tablename__ = "quotations"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = _org_col()
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100))
    quote_date: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    prices_include_vat: Mapped[bool | None] = mapped_column(Boolean)
    flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_quotations_org_id"),
        UniqueConstraint(
            "organisation_id", "id", "document_version_id", name="uq_quotations_org_id_version"
        ),
        UniqueConstraint(
            "organisation_id", "document_version_id", name="uq_quotations_org_version"
        ),
        ForeignKeyConstraint(
            ["organisation_id", "run_id", "document_version_id"],
            [
                "extraction_runs.organisation_id",
                "extraction_runs.id",
                "extraction_runs.document_version_id",
            ],
            name="fk_quotations_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "supplier_id"],
            ["suppliers.organisation_id", "suppliers.id"],
            name="fk_quotations_supplier",
        ),
    )


class QuotationItem(Base):
    __tablename__ = "quotation_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = _org_col()
    quotation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100))
    unit: Mapped[str | None] = mapped_column(String(30))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    raw_unit: Mapped[str | None] = mapped_column(String(50))
    raw_quantity: Mapped[str | None] = mapped_column(String(50))
    raw_price: Mapped[str | None] = mapped_column(String(50))
    flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    page_number: Mapped[int | None] = mapped_column(Integer)
    sheet: Mapped[str | None] = mapped_column(String(200))
    cell_range: Mapped[str | None] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unreviewed")
    original_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    corrected_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_quotation_items_org_id"),
        ForeignKeyConstraint(
            ["organisation_id", "quotation_id", "document_version_id"],
            ["quotations.organisation_id", "quotations.id", "quotations.document_version_id"],
            name="fk_quotation_items_quotation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "run_id", "document_version_id"],
            [
                "extraction_runs.organisation_id",
                "extraction_runs.id",
                "extraction_runs.document_version_id",
            ],
            name="fk_quotation_items_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "reviewed_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_quotation_items_reviewer_membership",
        ),
        Index("ix_quotation_items_version", "document_version_id", "source_order", "position"),
        Index("ix_quotation_items_quotation", "quotation_id"),
    )


class MatchSuggestion(Base):
    __tablename__ = "match_suggestions"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = _org_col()
    boq_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    quotation_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    classification: Mapped[str] = mapped_column(String(10), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="suggested")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("boq_item_id", "quotation_item_id", name="uq_match_pair"),
        CheckConstraint("status IN ('suggested', 'confirmed', 'rejected')", name="ck_match_status"),
        CheckConstraint("classification IN ('clear', 'ambiguous')", name="ck_match_classification"),
        ForeignKeyConstraint(
            ["organisation_id", "boq_item_id"],
            ["boq_items.organisation_id", "boq_items.id"],
            name="fk_match_boq_item",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "quotation_item_id"],
            ["quotation_items.organisation_id", "quotation_items.id"],
            name="fk_match_quotation_item",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "supplier_id"],
            ["suppliers.organisation_id", "suppliers.id"],
            name="fk_match_supplier",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "decided_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_match_decider_membership",
        ),
        Index(
            "uq_match_confirmed_per_boq_supplier",
            "boq_item_id",
            "supplier_id",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
        Index("ix_match_boq_item", "boq_item_id"),
        Index("ix_match_quotation_item", "quotation_item_id"),
    )
