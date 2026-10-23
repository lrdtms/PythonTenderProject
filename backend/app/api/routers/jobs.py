"""Processing job status and retry."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.modules.documents import public as documents
from app.modules.jobs import public as jobs
from app.modules.pipeline import public as pipeline

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=jobs.JobDTO)
def get_job(job_id: UUID, ctx: Ctx, session: DbSession):
    return jobs.get_job(session, ctx, job_id)


@router.post("/{job_id}/retry", response_model=jobs.JobDTO)
def retry_job(job_id: UUID, ctx: Ctx, session: DbSession):
    job = jobs.get_job(session, ctx, job_id)  # NotFound for another organisation
    documents.ensure_job_retry_allowed(session, ctx, job.job_type, job.subject_id)
    return jobs.retry_job(session, ctx, job_id)


@router.post("/{job_id}/cancel", response_model=jobs.JobDTO)
def cancel_job(job_id: UUID, ctx: Ctx, session: DbSession):
    job = jobs.get_job(session, ctx, job_id)  # NotFound for another organisation
    documents.ensure_job_cancel_allowed(session, ctx, job.job_type, job.subject_id)
    cancelled = jobs.cancel_job(session, ctx, job_id)
    if cancelled.status == "cancelled":
        pipeline.cancel_runs_for_job(session, ctx, job_id, skip_locked=True)
    return cancelled
