"""Pricing defaults, estimates and their lines.

Lines hold snapshots of the BoQ line and the chosen quotation price. `boq_item_id`,
`match_suggestion_id`, `quotation_item_id` and `supplier_id` are plain columns with no foreign
key, so a BoQ re-run, a match cascade or a supplier merge never fails on or deletes a line.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

ESTIMATE_STATUSES = ("draft", "reviewed", "approved")
MARKUP_BASES = ("cost", "selling_price")
PRICE_SOURCES = ("supplier", "manual", "excluded", "unresolved")


def _org_col() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("organisations.id"), nullable=False)


def _money4() -> Mapped[Decimal | None]:
    return mapped_column(Numeric(18, 4))


def _money2() -> Mapped[Decimal | None]:
    return mapped_column(Numeric(18, 2))


class PricingDefaults(Base):
    __tablename__ = "pricing_defaults"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), primary_key=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    markup_basis: Mapped[str] = mapped_column(String(15), nullable=False)
    default_markup_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("markup_basis IN ('cost', 'selling_price')", name="ck_defaults_basis"),
        CheckConstraint("vat_rate >= 0 AND vat_rate <= 100", name="ck_defaults_vat"),
        ForeignKeyConstraint(
            ["organisation_id", "updated_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_pricing_defaults_updater_membership",
        ),
    )


class Estimate(Base):
    __tablename__ = "estimates"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = _org_col()
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    markup_basis: Mapped[str] = mapped_column(String(15), nullable=False)
    markup_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    based_on_version: Mapped[int | None] = mapped_column(Integer)
    subtotal_cost: Mapped[Decimal | None] = _money2()
    markup_total: Mapped[Decimal | None] = _money2()
    subtotal_ex_vat: Mapped[Decimal | None] = _money2()
    vat_total: Mapped[Decimal | None] = _money2()
    total_inc_vat: Mapped[Decimal | None] = _money2()
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_estimates_org_id"),
        UniqueConstraint("organisation_id", "tender_id", "version", name="uq_estimates_version"),
        CheckConstraint("status IN ('draft', 'reviewed', 'approved')", name="ck_estimates_status"),
        CheckConstraint("markup_basis IN ('cost', 'selling_price')", name="ck_estimates_basis"),
        ForeignKeyConstraint(
            ["organisation_id", "tender_id"],
            ["tenders.organisation_id", "tenders.id"],
            name="fk_estimates_tender",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "created_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_estimates_creator_membership",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "reviewed_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_estimates_reviewer_membership",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "approved_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_estimates_approver_membership",
        ),
        Index(
            "uq_estimates_one_draft",
            "tender_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )


class EstimateLine(Base):
    __tablename__ = "estimate_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = _org_col()
    estimate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    boq_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section: Mapped[str | None] = mapped_column(String(200))
    item_no: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30))
    quantity: Mapped[Decimal | None] = _money4()
    price_source: Mapped[str] = mapped_column(String(12), nullable=False, default="unresolved")
    match_suggestion_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    supplier_name: Mapped[str | None] = mapped_column(String(200))
    quotation_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quoted_unit_price: Mapped[Decimal | None] = _money4()
    quoted_currency: Mapped[str | None] = mapped_column(String(3))
    quoted_includes_vat: Mapped[bool | None] = mapped_column(Boolean)
    unit_price_ex_vat: Mapped[Decimal | None] = _money4()
    labour_rate: Mapped[Decimal | None] = _money4()
    markup_override_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    exclude_reason: Mapped[str | None] = mapped_column(Text)
    unit_mismatch_acknowledged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    material_cost: Mapped[Decimal | None] = _money2()
    labour_cost: Mapped[Decimal | None] = _money2()
    cost: Mapped[Decimal | None] = _money2()
    markup: Mapped[Decimal | None] = _money2()
    total: Mapped[Decimal | None] = _money2()
    flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("estimate_id", "boq_item_id", name="uq_estimate_lines_boq_item"),
        CheckConstraint(
            "price_source IN ('supplier', 'manual', 'excluded', 'unresolved')",
            name="ck_estimate_lines_source",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "estimate_id"],
            ["estimates.organisation_id", "estimates.id"],
            name="fk_estimate_lines_estimate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "updated_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_estimate_lines_updater_membership",
        ),
        Index("ix_estimate_lines_estimate", "estimate_id", "position"),
    )
