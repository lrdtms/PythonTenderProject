"""Public surface of the jobs module."""

from app.kernel import JobCancelled

from .schemas import ClaimedJob, JobDTO
from .service import (
    cancel_job,
    claim_next,
    complete,
    enqueue,
    fail_permanently,
    fail_transiently,
    find_active_job,
    get_for_worker,
    get_job,
    heartbeat,
    is_cancelled,
    latest_job_for_subject,
    reap_exhausted,
    retry_job,
)

__all__ = [
    "ClaimedJob",
    "JobCancelled",
    "JobDTO",
    "cancel_job",
    "claim_next",
    "complete",
    "enqueue",
    "fail_permanently",
    "fail_transiently",
    "find_active_job",
    "get_for_worker",
    "get_job",
    "heartbeat",
    "is_cancelled",
    "latest_job_for_subject",
    "reap_exhausted",
    "retry_job",
]
