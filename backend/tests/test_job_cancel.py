"""Cancelling jobs: queued and running, idempotence, permissions, the worker stopping, the run."""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import select

from app.db.session import session_scope
from app.kernel import ProcessingFailed
from app.modules.audit.models import AuditEvent
from app.modules.checklist.models import Requirement
from app.modules.estimating.models import BoqItem
from app.modules.jobs import public as jobs
from app.modules.jobs.models import Job
from app.modules.jobs.repo import QueueRepo
from app.modules.pipeline.models import ExtractionRun
from app.worker import handlers
from app.worker.runner import JobHandler, process_one
from tests.conftest import add_member, make_pdf, make_tender, register, upload
from tests.test_extraction_pipeline import API, CLAUSE, boq_pdf, extraction, req_json
from tests.test_jobs import enqueue

JT = "extract_boq"  # ingest jobs cannot be cancelled; any other type with a random subject works


def cancel(actor, job_id):
    return actor.client.post(f"{API}/jobs/{job_id}/cancel")


def job_row(job_id) -> Job:
    with session_scope() as s:
        row = s.get(Job, UUID(str(job_id)))
        s.expunge(row)
        return row


def test_cancel_a_queued_job_and_the_worker_never_claims_it(admin) -> None:
    job = enqueue(admin, job_type=JT)
    r = cancel(admin, job.id)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert r.json()["completed_at"] is not None
    with session_scope() as s:
        assert jobs.claim_next(s, 60) is None
    assert process_one({}) is False


def test_cancel_is_idempotent_and_leaves_finished_jobs_alone(admin) -> None:
    job = enqueue(admin, job_type=JT)
    assert cancel(admin, job.id).status_code == 200
    again = cancel(admin, job.id)
    assert again.status_code == 200 and again.json()["status"] == "cancelled"
    done = enqueue(admin, job_type=JT)
    with session_scope() as s:
        jobs.claim_next(s, 60)
        jobs.complete(s, done.id, [])
    kept = cancel(admin, done.id)
    assert kept.status_code == 200 and kept.json()["status"] == "succeeded"
    assert job_row(done.id).status == "succeeded"


def test_cancel_frees_the_active_slot(admin) -> None:
    job = enqueue(admin, job_type=JT)
    cancel(admin, job.id)
    fresh = enqueue(admin, job.subject_id, job.job_type)
    assert fresh.id != job.id and fresh.status == "queued"


def test_cancel_permissions_and_isolation(admin) -> None:
    job = enqueue(admin, job_type=JT)
    reviewer = add_member(admin, "rev@example.com", "reviewer")
    manager = add_member(admin, "pm@example.com", "project_manager")
    assert cancel(reviewer, job.id).status_code == 403
    assert cancel(manager, job.id).status_code == 403
    other = register("other@example.com", org="Other Co")
    assert cancel(other, job.id).status_code == 404
    assert cancel(admin, "00000000-0000-0000-0000-000000000000").status_code == 404
    assert job_row(job.id).status == "queued"
    estimator = add_member(admin, "est@example.com", "estimator")
    assert cancel(estimator, job.id).status_code == 200


def test_cancel_writes_an_audit_event_with_ids_only(admin) -> None:
    job = enqueue(admin, job_type=JT)
    cancel(admin, job.id)
    with session_scope() as s:
        ev = s.scalars(select(AuditEvent).where(AuditEvent.action == "job_cancelled")).one()
    assert ev.entity_id == job.id and ev.entity_type == "job"
    assert ev.event_metadata == {
        "job_type": JT,
        "subject_id": str(job.subject_id),
        "old_status": "queued",
    }


def _ready_version():
    admin = register("canc@example.com")
    tid = make_tender(admin)
    body = upload(admin, tid, make_pdf(["Background. " + CLAUSE]), "t.pdf").json()
    assert process_one(handlers.HANDLERS) is True  # ingest; extraction is queued
    return admin, tid, body["version"]["id"]


def _cancelling(admin, job_type: str) -> dict[str, JobHandler]:
    """The real handlers, except `job_type` cancels its own job right after it starts."""
    real = handlers.HANDLERS[job_type]

    def run(session, ctx, job, progress):
        assert cancel(admin, job.id).status_code == 200
        return real.run(session, ctx, job, progress)

    return {**handlers.HANDLERS, job_type: replace(real, run=run)}


def test_a_running_job_stops_at_its_next_progress_and_stores_nothing(
    fake_llm, caplog: pytest.LogCaptureFixture
) -> None:
    fake_llm([req_json("must submit a valid tax clearance certificate")])
    admin, _, vid = _ready_version()
    caplog.set_level(logging.INFO, logger="worker")
    hs = _cancelling(admin, "extract_requirements")
    while process_one(hs):
        pass
    with session_scope() as s:
        req_job = s.scalars(select(Job).where(Job.job_type == "extract_requirements")).one()
        assert s.scalars(select(Requirement)).all() == []
        run = s.scalars(select(ExtractionRun).where(ExtractionRun.job_id == req_job.id)).one()
    assert req_job.status == "cancelled" and req_job.error_code is None
    assert req_job.attempt_count == 1  # not retried
    assert run.status == "cancelled" and run.finished_at is not None
    assert f"job {req_job.id} cancelled" in caplog.messages
    assert not any(
        r.levelno >= logging.WARNING and str(req_job.id) in r.message for r in caplog.records
    )
    kinds = {k["kind"]: k for k in extraction(admin, vid)["kinds"]}
    assert kinds["requirements"]["job"]["status"] == "cancelled"
    assert kinds["requirements"]["run"]["status"] == "cancelled"
    # extraction can be run again: the slot is free
    r = admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    assert r.status_code == 202
    again = {j["job_type"]: j for j in r.json()}["extract_requirements"]
    assert again["status"] == "queued" and again["id"] != str(req_job.id)


def test_a_job_cancelled_after_its_last_progress_commits_nothing(admin) -> None:
    job = enqueue(admin, job_type="late_cancel")
    subject = job.subject_id

    def run(session, ctx, j, progress):
        jobs.enqueue(session, ctx, "side_effect", "document_version", subject)
        assert cancel(admin, j.id).status_code == 200  # no progress() call follows
        return []

    assert process_one({"late_cancel": JobHandler(run=run)}) is True
    with session_scope() as s:
        assert s.scalars(select(Job).where(Job.job_type == "side_effect")).all() == []
    assert job_row(job.id).status == "cancelled"


def test_cancel_after_a_stale_claim_is_not_overwritten_by_complete(admin) -> None:
    job = enqueue(admin, job_type=JT)
    with session_scope() as s:
        jobs.claim_next(s, 60)
    assert cancel(admin, job.id).json()["status"] == "cancelled"
    with session_scope() as s:
        jobs.complete(s, job.id, [])
        with pytest.raises(jobs.JobCancelled):
            jobs.heartbeat(s, job.id, 1, 2, 60)
    assert job_row(job.id).status == "cancelled"


def _extraction_job_id(vid: str, job_type: str) -> UUID:
    with session_scope() as s:
        return s.scalars(
            select(Job.id).where(Job.job_type == job_type, Job.subject_id == UUID(vid))
        ).one()


def test_cancel_on_an_archived_tender_is_refused() -> None:
    admin, tid, vid = _ready_version()
    assert admin.client.post(f"{API}/tenders/{tid}/archive").status_code == 200
    job_id = _extraction_job_id(vid, "extract_boq")
    r = cancel(admin, job_id)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "tender_archived")
    assert job_row(job_id).status == "queued"


def test_an_ingest_job_cannot_be_cancelled(admin) -> None:
    tid = make_tender(admin)
    body = upload(admin, tid, make_pdf([CLAUSE]), "t.pdf").json()
    r = cancel(admin, body["job_id"])
    assert (r.status_code, r.json()["error"]["code"]) == (409, "job_not_cancellable")
    assert job_row(body["job_id"]).status == "queued"


def _boq_version():
    admin = register("boqc@example.com")
    tid = make_tender(admin)
    body = upload(admin, tid, boq_pdf(), "boq.pdf", "boq").json()
    assert process_one(handlers.HANDLERS) is True  # ingest
    return admin, body["version"]["id"]


def _no_boq_items() -> bool:
    with session_scope() as s:
        return s.scalars(select(BoqItem)).first() is None


def test_cancel_while_the_handler_holds_run_locks_does_not_deadlock() -> None:
    """The cancel runs from a second thread inside extract_boq's last progress call, when the
    handler transaction holds the run-row locks. A regression hangs, so the thread is timed."""
    admin, vid = _boq_version()
    real = handlers.HANDLERS["extract_boq"]
    outcome: dict[str, int] = {}

    def run(session, ctx, job, progress):
        def cancelling_progress(done, total):
            th = threading.Thread(
                target=lambda: outcome.update(code=cancel(admin, job.id).status_code)
            )
            th.start()
            th.join(timeout=20)
            outcome["hung"] = int(th.is_alive())
            progress(done, total)

        return real.run(session, ctx, job, cancelling_progress)

    hs = {**handlers.HANDLERS, "extract_boq": replace(real, run=run)}
    assert process_one(hs) is True
    assert outcome == {"code": 200, "hung": 0}
    job_id = _extraction_job_id(vid, "extract_boq")
    assert job_row(job_id).status == "cancelled"
    with session_scope() as s:
        run_row = s.scalars(select(ExtractionRun).where(ExtractionRun.job_id == job_id)).one()
    assert run_row.status == "cancelled"
    assert _no_boq_items()


def test_cancel_between_claim_and_on_start_leaves_no_open_run() -> None:
    admin, vid = _boq_version()
    real = handlers.HANDLERS["extract_boq"]

    def on_start(session, ctx, job):
        assert cancel(admin, job.id).status_code == 200  # before the run exists
        real.on_start(session, ctx, job)

    hs = {**handlers.HANDLERS, "extract_boq": replace(real, on_start=on_start)}
    assert process_one(hs) is True
    job_id = _extraction_job_id(vid, "extract_boq")
    with session_scope() as s:
        run_row = s.scalars(select(ExtractionRun).where(ExtractionRun.job_id == job_id)).one()
    assert job_row(job_id).status == "cancelled" and run_row.status == "cancelled"
    assert _no_boq_items()


@pytest.mark.parametrize("transient", [True, False])
def test_a_failure_after_a_cancel_does_not_overwrite_it(transient: bool) -> None:
    admin, vid = _boq_version()
    real = handlers.HANDLERS["extract_boq"]

    def run(session, ctx, job, progress):
        assert cancel(admin, job.id).status_code == 200
        raise ProcessingFailed("LLM_UNAVAILABLE", transient=transient)

    hs = {**handlers.HANDLERS, "extract_boq": replace(real, run=run)}
    assert process_one(hs) is True
    job_id = _extraction_job_id(vid, "extract_boq")
    row = job_row(job_id)
    assert row.status == "cancelled" and row.attempt_count == 1 and row.error_code is None
    with session_scope() as s:
        run_row = s.scalars(select(ExtractionRun).where(ExtractionRun.job_id == job_id)).one()
    assert run_row.status == "cancelled" and run_row.error_code is None
    # the user already asked again, then a stale requeue must be a no-op rather than a conflict
    r = admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    assert r.status_code == 202
    with session_scope() as s:
        QueueRepo(s).requeue(job_id, "X", 0)
    assert job_row(job_id).status == "cancelled"
