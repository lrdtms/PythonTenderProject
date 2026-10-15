"""The Postgres-backed job queue (ADR-0006)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

JOB_STATUSES = ("queued", "running", "succeeded", "succeeded_with_warnings", "failed", "cancelled")
ACTIVE_STATUSES = ("queued", "running")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(50))
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("organisation_id", "id", name="uq_jobs_org_id"),
        ForeignKeyConstraint(
            ["organisation_id", "created_by"],
            ["memberships.organisation_id", "memberships.user_id"],
            name="fk_jobs_creator_membership",
        ),
        # One active job per (type, subject): double clicks and retries cannot duplicate work.
        Index(
            "uq_jobs_active_subject",
            "job_type",
            "subject_id",
            unique=True,
            postgresql_where=text("status in ('queued', 'running')"),
        ),
        Index("ix_jobs_claim", "status", "run_after"),
    )
