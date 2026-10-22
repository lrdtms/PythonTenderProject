"""Run one job at a time: claim, execute a handler, record the outcome (ADR-0006).

Handlers do the work in one transaction. Progress and the final status are written in their own
short transactions so a failing handler cannot lose them. Logs carry IDs and error codes only,
never document text.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import session_scope, set_org
from app.kernel import JobCancelled, OrgContext, ProcessingFailed
from app.modules.jobs import public as jobs

log = logging.getLogger("worker")

ProgressFn = Callable[[int, int], None]
COMPLETE_RETRY_DELAYS = (1.0, 3.0)  # seconds between attempts to record a committed success


@dataclass(frozen=True)
class JobHandler:
    run: Callable[[Session, OrgContext, jobs.ClaimedJob, ProgressFn], list[dict[str, Any]]]
    # Called once when the job has definitively failed (not when it will be retried), including
    # when the reaper fails a job whose worker died on its last attempt.
    on_failure: Callable[[Session, OrgContext, jobs.ClaimedJob], None] | None = None
    # Called in its own short transaction right after the claim, before the long work, so
    # clients can see that the job is being worked on (e.g. a version becomes `processing`).
    on_start: Callable[[Session, OrgContext, jobs.ClaimedJob], None] | None = None
    # Called in its own short transaction when the job stopped because it was cancelled, after
    # the handler's transaction rolled back: closes records on_start left open (e.g. a run).
    on_cancel: Callable[[Session, OrgContext, jobs.ClaimedJob], None] | None = None


def _context(job: jobs.ClaimedJob) -> OrgContext:
    return OrgContext.system(job.organisation_id, job.created_by or UUID(int=0))


def process_one(handlers: dict[str, JobHandler]) -> bool:
    """Process the next runnable job. Returns False when the queue is empty."""
    lease = get_settings().job_lease_seconds
    _reap(handlers)
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
        if handler.on_start is not None:
            with session_scope() as session:
                set_org(session, ctx.organisation_id)
                handler.on_start(session, ctx, job)
        with session_scope() as session:
            set_org(session, ctx.organisation_id)
            warnings = handler.run(session, ctx, job, progress)
            if jobs.is_cancelled(session, job.id):  # cancelled after the last progress call
                raise JobCancelled
    except JobCancelled:
        # The cancel already set the status; the handler's transaction was rolled back, so no
        # results were stored. Not a failure: no retry, no failure hook, no completion.
        _stopped(handler, ctx, job)
        return True
    except ProcessingFailed as exc:
        if _cancelled_meanwhile(handler, ctx, job):
            return True
        _record_failure(handler, ctx, job, exc.error_code, exc.transient)
        return True
    except Exception as exc:  # noqa: BLE001 - an unexpected bug must not kill the worker loop
        transient = _is_transient(exc)
        code = "INFRASTRUCTURE" if transient else "UNEXPECTED"
        # No traceback and no exception message: either can carry document text (cell values in
        # a failed statement, parser messages). The type name and job id are enough to triage.
        log.error("job %s crashed error_type=%s code=%s", job.id, type(exc).__name__, code)
        if _cancelled_meanwhile(handler, ctx, job):
            return True
        _record_failure(handler, ctx, job, code, transient)
        return True
    _complete(job, warnings)
    return True


def _stopped(handler: JobHandler, ctx: OrgContext, job: jobs.ClaimedJob) -> None:
    """The job was cancelled: record nothing as a failure, only close what on_start opened."""
    if handler.on_cancel is not None:
        try:
            with session_scope() as session:
                set_org(session, ctx.organisation_id)
                handler.on_cancel(session, ctx, job)
        except Exception as exc:  # noqa: BLE001 - one bad hook must not stop the worker
            log.error("job %s cancel hook error_type=%s", job.id, type(exc).__name__)
    log.info("job %s cancelled", job.id)


def _cancelled_meanwhile(handler: JobHandler, ctx: OrgContext, job: jobs.ClaimedJob) -> bool:
    """A handler failing after its job was cancelled must not requeue or fail it."""
    with session_scope() as session:
        cancelled = jobs.is_cancelled(session, job.id)
    if cancelled:
        _stopped(handler, ctx, job)
    return cancelled


def _is_transient(exc: Exception) -> bool:
    """Infrastructure trouble (database connection, storage I/O) is retried with backoff
    (FR-65, ADR-0006); anything else is a bug or a bad file and fails permanently."""
    if isinstance(exc, OperationalError | InterfaceError):
        return True
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    return isinstance(exc, OSError)


def _complete(job: jobs.ClaimedJob, warnings: list[dict[str, Any]]) -> None:
    """Record success. The handler's work is already committed, so a failure here must never
    fail the job's subject: retry a few times, then leave the job running for the lease to
    reclaim (re-running a handler is idempotent)."""
    for delay in (0, *COMPLETE_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            with session_scope() as session:
                jobs.complete(session, job.id, warnings)
        except Exception as exc:  # noqa: BLE001 - retried below; never fails the subject
            log.error("job %s completion failed error_type=%s", job.id, type(exc).__name__)
            continue
        log.info("job %s finished warnings=%d", job.id, len(warnings))
        return
    log.error("job %s left running: its lease will expire and it will be reclaimed", job.id)


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


def _reap(handlers: dict[str, JobHandler]) -> None:
    """Fail jobs whose worker died on the last attempt, then run each one's failure hook in its
    own transaction (as the job's organisation), so e.g. the version does not stay `pending`."""
    with session_scope() as session:
        reaped = jobs.reap_exhausted(session)
    for job in reaped:
        log.warning("job %s -> failed code=LEASE_EXPIRED", job.id)
        handler = handlers.get(job.job_type)
        if handler is None or handler.on_failure is None:
            continue
        ctx = _context(job)
        try:
            with session_scope() as session:
                set_org(session, ctx.organisation_id)
                handler.on_failure(session, ctx, job)
        except Exception as exc:  # noqa: BLE001 - one bad hook must not stop the worker
            log.error("job %s failure hook error_type=%s", job.id, type(exc).__name__)
