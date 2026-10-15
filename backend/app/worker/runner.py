"""Run one job at a time: claim, execute a handler, record the outcome (ADR-0006).

Handlers do the work in one transaction. Progress and the final status are written in their own
short transactions so a failing handler cannot lose them. Logs carry IDs and error codes only,
never document text.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import session_scope, set_org
from app.kernel import OrgContext, ProcessingFailed
from app.modules.jobs import public as jobs

log = logging.getLogger("worker")

ProgressFn = Callable[[int, int], None]


@dataclass(frozen=True)
class JobHandler:
    run: Callable[[Session, OrgContext, jobs.ClaimedJob, ProgressFn], list[dict[str, Any]]]
    # Called once when the job has definitively failed (not when it will be retried).
    on_failure: Callable[[Session, OrgContext, jobs.ClaimedJob], None] | None = None


def _context(job: jobs.ClaimedJob) -> OrgContext:
    return OrgContext.system(job.organisation_id, job.created_by or UUID(int=0))


def process_one(handlers: dict[str, JobHandler]) -> bool:
    """Process the next runnable job. Returns False when the queue is empty."""
    lease = get_settings().job_lease_seconds
    with session_scope() as session:
        job = jobs.claim_next(session, lease)
    if job is None:
        return False

    handler = handlers.get(job.job_type)
    if handler is None:
        log.error("no handler for job_type=%s job=%s", job.job_type, job.id)
        with session_scope() as session:
            jobs.fail_permanently(session, job.id, "NO_HANDLER")
        return True

    ctx = _context(job)

    def progress(done: int, total: int) -> None:
        with session_scope() as session:
            jobs.heartbeat(session, job.id, done, total, lease)

    log.info("job %s started type=%s attempt=%s", job.id, job.job_type, job.attempt_count)
    try:
        with session_scope() as session:
            set_org(session, ctx.organisation_id)
            warnings = handler.run(session, ctx, job, progress)
        with session_scope() as session:
            jobs.complete(session, job.id, warnings)
        log.info("job %s finished warnings=%d", job.id, len(warnings))
    except ProcessingFailed as exc:
        _record_failure(handler, ctx, job, exc.error_code, exc.transient)
    except Exception as exc:  # noqa: BLE001 - an unexpected bug must not kill the worker loop
        # No traceback and no exception message: either can carry document text (cell values in
        # a failed statement, parser messages). The type name and job id are enough to triage.
        log.error("job %s crashed error_type=%s code=UNEXPECTED", job.id, type(exc).__name__)
        _record_failure(handler, ctx, job, "UNEXPECTED", transient=False)
    return True


def _record_failure(
    handler: JobHandler, ctx: OrgContext, job: jobs.ClaimedJob, code: str, transient: bool
) -> None:
    with session_scope() as session:
        if transient:
            status = jobs.fail_transiently(session, job, code)
        else:
            jobs.fail_permanently(session, job.id, code)
            status = "failed"
        if status == "failed" and handler.on_failure is not None:
            set_org(session, ctx.organisation_id)
            handler.on_failure(session, ctx, job)
    log.warning("job %s -> %s code=%s", job.id, status, code)
