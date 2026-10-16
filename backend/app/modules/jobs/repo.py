"""Job queue data access. Claiming runs outside any organisation (system level)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.scoped import ScopedRepository

from .models import ACTIVE_STATUSES, Job


class JobRepo(ScopedRepository[Job]):
    model = Job

    def latest_for_subject(self, subject_id: UUID, job_type: str | None = None) -> Job | None:
        where = [Job.subject_id == subject_id]
        if job_type is not None:
            where.append(Job.job_type == job_type)
        rows = self.find(*where, order_by=desc(Job.created_at), limit=1)
        return rows[0] if rows else None

    def active(self, job_type: str, subject_id: UUID) -> Job | None:
        rows = self.find(
            Job.job_type == job_type,
            Job.subject_id == subject_id,
            Job.status.in_(ACTIVE_STATUSES),
            limit=1,
        )
        return rows[0] if rows else None

    def enqueue(
        self,
        job_type: str,
        subject_type: str,
        subject_id: UUID,
        payload: dict[str, Any] | None,
        max_attempts: int = 3,
    ) -> Job:
        """Insert a job, or return the already-active one for the same (type, subject)."""
        stmt = (
            pg_insert(Job)
            .values(
                organisation_id=self.ctx.organisation_id,
                job_type=job_type,
                subject_type=subject_type,
                subject_id=subject_id,
                payload=payload or {},
                created_by=self.ctx.user_id,
                status="queued",
                max_attempts=max_attempts,
            )
            .on_conflict_do_nothing(
                index_elements=["job_type", "subject_id"],
                index_where=text("status in ('queued', 'running')"),
            )
            .returning(Job.id)
        )
        new_id = self.session.scalar(stmt)
        if new_id is not None:
            return self.get(new_id)
        existing = self.find(
            Job.job_type == job_type,
            Job.subject_id == subject_id,
            Job.status.in_(ACTIVE_STATUSES),
            limit=1,
        )
        return existing[0]


class QueueRepo:
    """Worker-side operations (not organisation-scoped: the worker serves every organisation)."""

    def __init__(self, session: Session):
        self.session = session

    def reap_exhausted(self) -> list[Job]:
        """Running jobs whose lease expired and that used all attempts become failed. Returns
        them, so the worker can run each handler's failure hook (e.g. mark the version failed)."""
        reap = text(
            "UPDATE jobs SET status='failed', error_code='LEASE_EXPIRED', completed_at=now(), "
            "leased_until=NULL WHERE status='running' AND leased_until < now() "
            "AND attempt_count >= max_attempts RETURNING id"
        )
        ids = self.session.execute(reap).scalars().all()
        if not ids:
            return []
        self.session.expire_all()
        return list(self.session.scalars(select(Job).where(Job.id.in_(ids))).all())

    def claim(self, lease_seconds: int) -> Job | None:
        """Atomically take the next runnable job (queued, or running with an expired lease).
        Exhausted jobs are not claimable; reap_exhausted fails them."""
        row = self.session.execute(
            text(
                """
                WITH next AS (
                    SELECT id FROM jobs
                    WHERE (status = 'queued' AND run_after <= now())
                       OR (status = 'running' AND leased_until < now()
                           AND attempt_count < max_attempts)
                    ORDER BY run_after, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE jobs SET status = 'running',
                                attempt_count = attempt_count + 1,
                                leased_until = now() + make_interval(secs => :lease),
                                started_at = COALESCE(started_at, now())
                FROM next WHERE jobs.id = next.id
                RETURNING jobs.id
                """
            ),
            {"lease": lease_seconds},
        ).first()
        if row is None:
            return None
        self.session.expire_all()
        return self.session.get(Job, row[0])

    def heartbeat(self, job_id: UUID, done: int, total: int, lease_seconds: int) -> None:
        self.session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(
                progress_done=done,
                progress_total=total,
                leased_until=datetime.now(UTC) + timedelta(seconds=lease_seconds),
            )
        )

    def finish(
        self, job_id: UUID, status: str, warnings: list[Any], error_code: str | None
    ) -> None:
        self.session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=status,
                warnings=warnings,
                error_code=error_code,
                completed_at=datetime.now(UTC),
                leased_until=None,
            )
        )

    def requeue(self, job_id: UUID, error_code: str, delay_seconds: int) -> None:
        self.session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="queued",
                error_code=error_code,
                run_after=datetime.now(UTC) + timedelta(seconds=delay_seconds),
                leased_until=None,
            )
        )

    def get(self, job_id: UUID) -> Job | None:
        self.session.expire_all()
        return self.session.get(Job, job_id)
