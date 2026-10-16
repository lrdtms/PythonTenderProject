"""Tender requirements extracted from a document version (reviewed in Slice 4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk


class Requirement(Base):
    __tablename__ = "requirements"

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
    description: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    mandatory_status: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_status: Mapped[str] = mapped_column(String(25), nullable=False, default="verified")
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    quote_start: Mapped[int | None] = mapped_column(Integer)
    quote_end: Mapped[int | None] = mapped_column(Integer)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unreviewed")
    original_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    corrected_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ai_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    suggested_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        ForeignKeyConstraint(
            ["organisation_id", "run_id", "document_version_id"],
            [
                "extraction_runs.organisation_id",
                "extraction_runs.id",
                "extraction_runs.document_version_id",
            ],
            name="fk_requirements_run",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "reviewed_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_requirements_reviewer_membership",
        ),
        Index("ix_requirements_version", "document_version_id", "source_order", "position"),
    )
