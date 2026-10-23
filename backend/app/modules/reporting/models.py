"""Exports: one row per generated file (Excel estimate or PDF checklist report)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, uuid_pk

EXPORT_KINDS = ("estimate_xlsx", "checklist_pdf")
EXPORT_LABELS = ("draft", "reviewed", "approved")


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), nullable=False
    )
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    estimate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    estimate_version: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(10), nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Stored explicitly (no server default): the very value printed inside the file.
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_exports_org_id"),
        CheckConstraint("kind IN ('estimate_xlsx', 'checklist_pdf')", name="ck_exports_kind"),
        CheckConstraint("label IN ('draft', 'reviewed', 'approved')", name="ck_exports_label"),
        CheckConstraint(
            "(kind = 'estimate_xlsx' AND estimate_id IS NOT NULL AND estimate_version IS NOT NULL)"
            " OR (kind = 'checklist_pdf' AND estimate_id IS NULL AND estimate_version IS NULL)",
            name="ck_exports_estimate_cols",
        ),
        CheckConstraint(
            "kind <> 'checklist_pdf' OR label IN ('draft', 'approved')",
            name="ck_exports_checklist_label",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "tender_id"],
            ["tenders.organisation_id", "tenders.id"],
            name="fk_exports_tender",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "estimate_id"],
            ["estimates.organisation_id", "estimates.id"],
            name="fk_exports_estimate",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "generated_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_exports_generator_membership",
        ),
        Index("ix_exports_tender", "organisation_id", "tender_id", "generated_at"),
    )
