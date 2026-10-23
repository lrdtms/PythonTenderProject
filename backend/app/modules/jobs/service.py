"""Job use cases: enqueue, inspect, retry (organisation side) and claim/finish (worker side)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import Conflict, OrgContext, Permission
from app.modules.audit import public as audit

from .models import Job
from .repo import JobRepo, QueueRepo
from .schemas import ClaimedJob, JobDTO

BACKOFF_SECONDS = 30


def _dto(job: Job) -> JobDTO:
    return JobDTO.model_validate(job, from_attributes=True)


# --- organisation side -------------------------------------------------------------------------


def enqueue(
    session: Session,
    ctx: OrgContext,
    job_type: str,
    subject_type: str,
    subject_id: UUID,
    payload: dict[str, Any] | None = None,
) -> JobDTO:
    """Create a job, or return the active one for the same subject (no duplicate work)."""
    return _dto(JobRepo(session, ctx).enqueue(job_type, subject_type, subject_id, payload))


def get_job(session: Session, ctx: OrgContext, job_id: UUID) -> JobDTO:
    ctx.require(Permission.READ)
    return _dto(JobRepo(session, ctx).get(job_id))


def latest_job_for_subject(
    session: Session, ctx: OrgContext, subject_id: UUID, job_type: str | None = None
) -> JobDTO | None:
    job = JobRepo(session, ctx).latest_for_subject(subject_id, job_type)
    return _dto(job) if job else None


def find_active_job(
    session: Session, ctx: OrgContext, job_type: str, subject_id: UUID
) -> JobDTO | None:
    job = JobRepo(session, ctx).active(job_type, subject_id)
    return _dto(job) if job else None


def retry_job(session: Session, ctx: OrgContext, job_id: UUID) -> JobDTO:
    """Put a failed job back in the queue (FR-16). If another job is already active for the same
    subject, return that one instead of creating a duplicate."""
    ctx.require(Permission.UPLOAD_DOCUMENTS)
    repo = JobRepo(session, ctx)
    job = repo.get(job_id)
    if job.status != "failed":
        raise Conflict("Only failed jobs can be retried.")
    fresh = repo.enqueue(job.job_type, job.subject_type, job.subject_id, job.payload)
    return _dto(fresh)


def cancel_job(session: Session, ctx: OrgContext, job_id: UUID) -> JobDTO:
    """Cancel a queued or running job. A job that already finished is returned unchanged. A
    running job notices at its next progress heartbeat and stops without storing anything."""
    ctx.require(Permission.REVIEW_DATA)
    job, previous = JobRepo(session, ctx).cancel(job_id)  # NotFound for another organisation
    if previous is not None:
        audit.record(
            session,
            ctx,
            "job",
            job.id,
            "job_cancelled",
            {"job_type": job.job_type, "subject_id": str(job.subject_id), "old_status": previous},
        )
    return _dto(job)


# --- worker side (system level) ----------------------------------------------------------------


def _claimed(job: Job) -> ClaimedJob:
    return ClaimedJob(
        id=job.id,
        organisation_id=job.organisation_id,
        job_type=job.job_type,
        subject_type=job.subject_type,
        subject_id=job.subject_id,
        payload=dict(job.payload),
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        created_by=job.created_by,
    )


def reap_exhausted(session: Session) -> list[ClaimedJob]:
    """Fail running jobs whose lease expired with no attempts left (LEASE_EXPIRED: the worker
    died on the last attempt). The caller runs each handler's failure hook."""
    return [_claimed(job) for job in QueueRepo(session).reap_exhausted()]


def claim_next(session: Session, lease_seconds: int) -> ClaimedJob | None:
    job = QueueRepo(session).claim(lease_seconds)
    return _claimed(job) if job is not None else None


def heartbeat(session: Session, job_id: UUID, done: int, total: int, lease_seconds: int) -> None:
    QueueRepo(session).heartbeat(job_id, done, total, lease_seconds)


def is_cancelled(session: Session, job_id: UUID) -> bool:
    return QueueRepo(session).status_of(job_id) == "cancelled"


def complete(session: Session, job_id: UUID, warnings: list[Any]) -> None:
    status = "succeeded_with_warnings" if warnings else "succeeded"
    QueueRepo(session).finish(job_id, status, warnings, None)


def fail_permanently(session: Session, job_id: UUID, error_code: str) -> None:
    QueueRepo(session).finish(job_id, "failed", [], error_code)


def fail_transiently(session: Session, job: ClaimedJob, error_code: str) -> str:
    """Retry later with backoff, or fail when attempts are used up. Returns the new status."""
    repo = QueueRepo(session)
    if job.attempt_count >= job.max_attempts:
        repo.finish(job.id, "failed", [], error_code)
        return "failed"
    repo.requeue(job.id, error_code, BACKOFF_SECONDS * job.attempt_count)
    return "queued"


def get_for_worker(session: Session, job_id: UUID) -> JobDTO | None:
    """System-level, not organisation-scoped: never call it from a router. For the worker and
    tests only; API code uses get_job, which is scoped to the caller's organisation."""
    job = QueueRepo(session).get(job_id)
    return _dto(job) if job else None
