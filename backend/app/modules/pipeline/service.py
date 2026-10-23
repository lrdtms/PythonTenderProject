"""Run lifecycle. The worker creates a run when a job starts and closes it when the job ends."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import Conflict, NotFound, OrgContext, Permission
from app.modules.documents import public as documents
from app.modules.jobs import public as jobs

from .models import ExtractionRun
from .repo import RunRepo
from .routing import KIND_OF_JOB, job_types_for_kind
from .schemas import ExtractionStatusDTO, KindStatusDTO, RunDTO


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
    if run is None or run.status == "cancelled":
        return
    run.status, run.error_code = "failed", error_code
    run.finished_at = datetime.now(UTC)
    session.flush()


def cancel_runs_for_job(
    session: Session, ctx: OrgContext, job_id: UUID, *, skip_locked: bool = False
) -> None:
    """Close the run of a cancelled job so the status panel does not show it as still working.
    A run that already finished is left as it is. The API passes `skip_locked`: a running
    handler may hold the run's lock, and waiting for it could deadlock with the worker's own
    heartbeat; the worker closes that run itself when it stops (the handler's on_cancel hook)."""
    for run in RunRepo(session, ctx).locked_for_job(job_id, skip_locked=skip_locked):
        if run.status in ("queued", "running"):
            run.status = "cancelled"
            run.finished_at = datetime.now(UTC)
    session.flush()


def current_runs(session: Session, ctx: OrgContext, version_id: UUID) -> dict[str, RunDTO]:
    ctx.require(Permission.READ)
    return {k: _dto(r) for k, r in RunRepo(session, ctx).current_for_version(version_id).items()}


READY = ("ready", "ready_with_warnings")


def request_extraction(
    session: Session, ctx: OrgContext, version_id: UUID, deep_scan: bool
) -> list[jobs.JobDTO]:
    """Queue the extraction jobs for this version's document kind. Idempotent while a job of
    the same type is active; asking for different options while one runs is a conflict."""
    ctx.require(Permission.REVIEW_DATA)
    info = documents.processing_info(session, ctx, version_id)  # NotFound for another org
    if info.tender_archived:
        raise Conflict(
            "This tender is archived. Re-open it before extracting.", code="tender_archived"
        )
    if documents.get_version(session, ctx, version_id).processing_status not in READY:
        raise Conflict("The document has not finished processing.", code="not_processed")
    out: list[jobs.JobDTO] = []
    for job_type in job_types_for_kind(info.kind):
        active = jobs.find_active_job(session, ctx, job_type, version_id)
        if active is not None:
            if bool(active.payload.get("deep_scan")) != deep_scan:
                raise Conflict(
                    "An extraction with different options is already running.",
                    code="extraction_options_conflict",
                )
            out.append(active)
            continue
        out.append(
            jobs.enqueue(
                session, ctx, job_type, "document_version", version_id, {"deep_scan": deep_scan}
            )
        )
    return out


def extraction_status(session: Session, ctx: OrgContext, version_id: UUID) -> ExtractionStatusDTO:
    ctx.require(Permission.READ)
    documents.get_version(session, ctx, version_id)  # NotFound for another organisation
    runs = current_runs(session, ctx, version_id)
    kinds = []
    for job_type, kind in KIND_OF_JOB.items():
        job = jobs.latest_job_for_subject(session, ctx, version_id, job_type)
        kinds.append(KindStatusDTO(kind=kind, job=job, run=runs.get(kind)))
    return ExtractionStatusDTO(kinds=kinds)
