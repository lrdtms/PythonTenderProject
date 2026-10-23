"""Plans and each organisation's chosen plan (mocked billing: no payments exist)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Plan(Base):
    """Reference data seeded by the migration; not organisation-owned."""

    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    max_tenders: Mapped[int] = mapped_column(Integer, nullable=False)
    max_uploads_per_month: Mapped[int] = mapped_column(Integer, nullable=False)
    max_storage_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    max_exports_per_month: Mapped[int] = mapped_column(Integer, nullable=False)
    max_members: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("max_tenders > 0", name="max_tenders_positive"),
        CheckConstraint("max_uploads_per_month > 0", name="max_uploads_positive"),
        CheckConstraint("max_storage_mb > 0", name="max_storage_positive"),
        CheckConstraint("max_exports_per_month > 0", name="max_exports_positive"),
        CheckConstraint("max_members > 0", name="max_members_positive"),
    )


class OrganisationPlan(Base):
    """One row per organisation that has ever chosen a plan; no row means the default plan."""

    __tablename__ = "organisation_plans"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), primary_key=True
    )
    plan_code: Mapped[str] = mapped_column(String(20), ForeignKey("plans.code"), nullable=False)
    changed_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organisation_id", "changed_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_organisation_plans_changer_membership",
        ),
    )
