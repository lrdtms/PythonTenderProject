"""One row per extraction run (ADR-0006 addendum): status, warnings, counts, versions."""

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
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

RUN_KINDS = ("boq", "requirements", "quotation")
RUN_STATUSES = ("queued", "running", "succeeded", "succeeded_with_warnings", "failed")


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="queued")
    deep_scan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    filter_version: Mapped[str | None] = mapped_column(String(20))
    schema_version: Mapped[str | None] = mapped_column(String(20))
    model: Mapped[str | None] = mapped_column(String(100))
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = created_at_col()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "organisation_id", "id", "document_version_id", name="uq_extraction_runs_org_id_version"
        ),
        UniqueConstraint("job_id", "kind", name="uq_extraction_runs_job_kind"),
        ForeignKeyConstraint(
            ["organisation_id", "document_version_id"],
            ["document_versions.organisation_id", "document_versions.id"],
            name="fk_extraction_runs_version",
        ),
        ForeignKeyConstraint(
            ["organisation_id", "job_id"],
            ["jobs.organisation_id", "jobs.id"],
            name="fk_extraction_runs_job",
        ),
        Index("ix_extraction_runs_version_kind", "document_version_id", "kind", "created_at"),
    )
