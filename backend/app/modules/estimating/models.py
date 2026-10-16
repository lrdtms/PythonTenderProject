"""BoQ items extracted from a document version (reviewed in Slice 4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

REVIEW_STATUSES = ("unreviewed", "confirmed", "corrected", "rejected")


class BoqItem(Base):
    __tablename__ = "boq_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    section: Mapped[str | None] = mapped_column(String(300))
    item_no: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    raw_unit: Mapped[str | None] = mapped_column(String(50))
    raw_quantity: Mapped[str | None] = mapped_column(String(50))
    flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    page_number: Mapped[int | None] = mapped_column(Integer)
    sheet: Mapped[str | None] = mapped_column(String(200))
    cell_range: Mapped[str | None] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unreviewed")
    original_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    corrected_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ai_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    suggested_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_boq_items_org_id"),
        ForeignKeyConstraint(
            ["organisation_id", "run_id", "document_version_id"],
            [
                "extraction_runs.organisation_id",
                "extraction_runs.id",
                "extraction_runs.document_version_id",
            ],
            name="fk_boq_items_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "reviewed_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_boq_items_reviewer_membership",
        ),
        Index("ix_boq_items_version", "document_version_id", "source_order", "position"),
    )
