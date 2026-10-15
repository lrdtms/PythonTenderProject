"""Tender workspaces."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

TENDER_STATUSES = ("preparing", "in_review", "ready", "submitted", "archived")


class Tender(Base):
    __tablename__ = "tenders"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(100))
    client_name: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    closing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="preparing")
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_tenders_org_id"),
        # The creator must be a member of the same organisation.
        ForeignKeyConstraint(
            ["organisation_id", "created_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_tenders_creator_membership",
        ),
    )
