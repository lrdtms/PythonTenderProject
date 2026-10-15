"""Run lifecycle. The worker creates a run when a job starts and closes it when the job ends."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import NotFound, OrgContext, Permission
from app.modules.jobs import public as jobs

from .models import ExtractionRun
from .repo import RunRepo
from .schemas import RunDTO


def _dto(run: ExtractionRun) -> RunDTO:
    return RunDTO.model_validate(run, from_attributes=True)


def start_run(
    session: Session,
    ctx: OrgContext,
    job: jobs.ClaimedJob,
    kind: str,
    *,
    deep_scan: bool,
    prompt_version: str | None,
    filter_version: str | None,
    schema_version: str | None,
    model: str | None,
) -> RunDTO:
    """Create the run for this job, or reset it when the job is being retried."""
    repo = RunRepo(session, ctx)
    run = repo.for_job(job.id, kind)
    if run is None:
        run = repo.add(ExtractionRun(document_version_id=job.subject_id, job_id=job.id, kind=kind))
    run.status = "running"
    run.deep_scan = deep_scan
    run.prompt_version, run.filter_version = prompt_version, filter_version
    run.schema_version, run.model = schema_version, model
    run.warnings, run.counts, run.error_code = [], {}, None
    run.started_at, run.finished_at = datetime.now(UTC), None
    session.flush()
    return _dto(run)


def run_for_job(session: Session, ctx: OrgContext, job_id: UUID, kind: str) -> RunDTO:
    run = RunRepo(session, ctx).for_job(job_id, kind)
    if run is None:
        raise NotFound("Extraction run not found")
    return _dto(run)


def lock_runs(session: Session, ctx: OrgContext, version_id: UUID, kind: str) -> None:
    RunRepo(session, ctx).lock_version(version_id, kind)


def finish_run(
    session: Session,
    ctx: OrgContext,
    job_id: UUID,
    kind: str,
    warnings: list[dict[str, Any]],
    counts: dict[str, Any],
) -> None:
    run = RunRepo(session, ctx).for_job(job_id, kind)
    if run is None:
        raise NotFound("Extraction run not found")
    run.status = "succeeded_with_warnings" if warnings else "succeeded"
    run.warnings, run.counts = warnings, counts
    run.finished_at = datetime.now(UTC)
    session.flush()


def fail_run(session: Session, ctx: OrgContext, job_id: UUID, kind: str, error_code: str) -> None:
    """Failure hook: also covers the reaper path. Creates nothing if the run never started."""
    run = RunRepo(session, ctx).for_job(job_id, kind)
    if run is None:
        return
    run.status, run.error_code = "failed", error_code
    run.finished_at = datetime.now(UTC)
    session.flush()


def current_runs(session: Session, ctx: OrgContext, version_id: UUID) -> dict[str, RunDTO]:
    ctx.require(Permission.READ)
    return {k: _dto(r) for k, r in RunRepo(session, ctx).current_for_version(version_id).items()}
