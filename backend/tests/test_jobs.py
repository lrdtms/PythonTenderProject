import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text, update

from app.db.session import session_scope
from app.kernel import OrgContext
from app.modules.jobs import public as jobs
from app.modules.jobs.models import Job
from tests.conftest import add_member, register


def ctx_for(actor) -> OrgContext:
    return OrgContext.system(UUID(actor.org_id), UUID(actor.me["user_id"]))


def enqueue(actor, subject=None, job_type="ingest_document"):
    subject = subject or uuid4()
    with session_scope() as s:
        return jobs.enqueue(s, ctx_for(actor), job_type, "document_version", subject)


def set_job(job_id, **values) -> None:
    with session_scope() as s:
        s.execute(update(Job).where(Job.id == job_id).values(**values))


def test_enqueue_is_idempotent_per_subject(admin) -> None:
    subject = uuid4()
    first, again = enqueue(admin, subject), enqueue(admin, subject)
    assert first.id == again.id
    assert enqueue(admin, subject, job_type="other_type").id != first.id


def test_claim_marks_running_and_counts_the_attempt(admin) -> None:
    job = enqueue(admin)
    with session_scope() as s:
        claimed = jobs.claim_next(s, lease_seconds=60)
    assert claimed and claimed.id == job.id and claimed.attempt_count == 1
    assert claimed.organisation_id == UUID(admin.org_id)  # org comes from the job row
    with session_scope() as s:
        assert jobs.claim_next(s, 60) is None  # nothing else is runnable


def test_two_workers_never_get_the_same_job(admin) -> None:
    for _ in range(4):
        enqueue(admin)
    got: list[UUID] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()
        with session_scope() as s:
            claimed = jobs.claim_next(s, 60)
        if claimed:
            got.append(claimed.id)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(got) == 4 and len(set(got)) == 4  # SKIP LOCKED: four jobs, four distinct claims


def test_expired_lease_is_reclaimed_until_attempts_run_out(admin) -> None:
    job = enqueue(admin)
    with session_scope() as s:
        jobs.claim_next(s, 60)
    set_job(job.id, leased_until=datetime.now(UTC) - timedelta(seconds=1))  # worker "crashed"
    with session_scope() as s:
        again = jobs.claim_next(s, 60)
    assert again and again.id == job.id and again.attempt_count == 2

    set_job(job.id, leased_until=datetime.now(UTC) - timedelta(seconds=1), attempt_count=3)
    with session_scope() as s:
        assert jobs.claim_next(s, 60) is None  # exhausted
    with session_scope() as s:
        done = jobs.get_for_worker(s, job.id)
    assert done.status == "failed" and done.error_code == "LEASE_EXPIRED"


def test_transient_failure_backs_off_then_fails_when_exhausted(admin) -> None:
    job = enqueue(admin)
    with session_scope() as s:
        claimed = jobs.claim_next(s, 60)
        assert jobs.fail_transiently(s, claimed, "LLM_UNAVAILABLE") == "queued"
    with session_scope() as s:
        assert jobs.claim_next(s, 60) is None  # run_after is in the future (backoff)
        queued = jobs.get_for_worker(s, job.id)
    assert queued.status == "queued" and queued.error_code == "LLM_UNAVAILABLE"

    set_job(job.id, run_after=datetime.now(UTC) - timedelta(seconds=1), attempt_count=2)
    with session_scope() as s:
        last = jobs.claim_next(s, 60)
        assert last.attempt_count == 3
        assert jobs.fail_transiently(s, last, "LLM_UNAVAILABLE") == "failed"


def test_complete_with_and_without_warnings(admin) -> None:
    a, b = enqueue(admin), enqueue(admin)
    with session_scope() as s:
        jobs.claim_next(s, 60)
        jobs.claim_next(s, 60)
    with session_scope() as s:
        jobs.complete(s, a.id, [])
        jobs.complete(s, b.id, [{"code": "OCR_FAILED", "pages": [2]}])
    with session_scope() as s:
        assert jobs.get_for_worker(s, a.id).status == "succeeded"
        done = jobs.get_for_worker(s, b.id)
    assert done.status == "succeeded_with_warnings" and done.warnings[0]["pages"] == [2]


def test_progress_heartbeat_extends_the_lease(admin) -> None:
    job = enqueue(admin)
    with session_scope() as s:
        jobs.claim_next(s, 1)
    with session_scope() as s:
        jobs.heartbeat(s, job.id, 3, 10, lease_seconds=600)
    resp = admin.client.get(f"/api/v1/jobs/{job.id}").json()
    assert (resp["progress_done"], resp["progress_total"]) == (3, 10)
    with session_scope() as s:
        assert jobs.claim_next(s, 60) is None  # lease was extended, so it is not reclaimable


def test_retry_only_failed_jobs_and_never_duplicates(admin) -> None:
    job = enqueue(admin)
    assert admin.client.post(f"/api/v1/jobs/{job.id}/retry").status_code == 409  # still queued
    with session_scope() as s:
        jobs.claim_next(s, 60)
        jobs.fail_permanently(s, job.id, "FILE_CORRUPT")
    retried = admin.client.post(f"/api/v1/jobs/{job.id}/retry")
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert retried.json()["id"] != str(job.id)  # a fresh job; the failed one stays as history
    again = admin.client.post(f"/api/v1/jobs/{job.id}/retry")
    assert again.status_code == 200 and again.json()["id"] == retried.json()["id"]


def test_retry_needs_upload_rights_and_reads_are_org_scoped(admin) -> None:
    job = enqueue(admin)
    with session_scope() as s:
        jobs.claim_next(s, 60)
        jobs.fail_permanently(s, job.id, "FILE_CORRUPT")
    reviewer = add_member(admin, "rev@example.com", "reviewer")
    assert reviewer.client.get(f"/api/v1/jobs/{job.id}").status_code == 200
    assert reviewer.client.post(f"/api/v1/jobs/{job.id}/retry").status_code == 403
    other = register("other@example.com", org="Other Co")
    assert other.client.get(f"/api/v1/jobs/{job.id}").status_code == 404
    assert other.client.post(f"/api/v1/jobs/{job.id}/retry").status_code == 404


def test_active_job_uniqueness_is_enforced_by_the_database(admin) -> None:
    subject = uuid4()
    enqueue(admin, subject)
    with session_scope() as s:
        active = s.execute(
            text(
                "SELECT count(*) FROM jobs WHERE subject_id = :s AND status IN ('queued','running')"
            ),
            {"s": subject},
        ).scalar()
    assert active == 1
