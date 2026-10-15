"""Ingest end to end: upload through the API, run the worker, read pages and search."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.db.session import session_scope
from app.infrastructure.storage import get_storage
from app.kernel import OrgContext, ProcessingFailed
from app.modules.audit.models import AuditEvent
from app.modules.jobs.models import Job
from app.modules.knowledge import public as knowledge
from app.modules.knowledge.models import DocumentChunk, DocumentPage
from app.worker import handlers
from app.worker.runner import process_one
from tests.conftest import (
    make_csv,
    make_docx,
    make_encrypted_pdf,
    make_pdf,
    make_scanned_pdf,
    make_tender,
    make_xlsx,
    upload,
)

API = "/api/v1"


def run_worker() -> bool:
    return process_one(handlers.HANDLERS)


def get_job(actor, job_id: str) -> dict:
    r = actor.client.get(f"{API}/jobs/{job_id}")
    assert r.status_code == 200, r.text
    return r.json()


def get_version(actor, document_id: str, version_id: str) -> dict:
    versions = actor.client.get(f"{API}/documents/{document_id}/versions").json()
    return next(v for v in versions if v["id"] == version_id)


def upload_and_ingest(actor, tid: str, data: bytes, name: str = "tender.pdf") -> dict:
    body = upload(actor, tid, data, name).json()
    assert run_worker() is True
    return body


class FakeOcr:
    def __init__(self, text: str = "Scanned tender clause", confidence: float = 90.0):
        self.text, self.confidence = text, confidence

    def available(self) -> bool:
        return True

    def run(self, png: bytes) -> tuple[str, float]:
        return self.text, self.confidence


class FailingOcr(FakeOcr):
    def run(self, png: bytes) -> tuple[str, float]:
        raise knowledge.OcrFailed("boom")


def use_ocr(monkeypatch, runner) -> None:
    monkeypatch.setattr(handlers, "_ocr", lambda: runner)


def test_happy_path_pages_and_search(admin) -> None:
    tid = make_tender(admin)
    body = upload_and_ingest(
        admin,
        tid,
        make_pdf(["Cable tray installation in the main hall.", "Switchgear and earthing."]),
    )
    job = get_job(admin, str(body["job_id"]))
    assert job["status"] == "succeeded" and job["warnings"] == []
    vid, did = body["version"]["id"], body["document"]["id"]
    assert get_version(admin, did, vid)["processing_status"] == "ready"

    pages = admin.client.get(f"{API}/document-versions/{vid}/pages").json()
    assert [p["page_number"] for p in pages] == [1, 2]
    assert all(p["char_count"] > 0 and p["text_source"] == "embedded" for p in pages)

    page1 = admin.client.get(f"{API}/document-versions/{vid}/pages/1").json()
    assert "Cable tray installation" in page1["text"]
    assert admin.client.get(f"{API}/document-versions/{vid}/pages/3").status_code == 404

    hits = admin.client.get(f"{API}/tenders/{tid}/search", params={"q": "earthing"}).json()
    assert len(hits) == 1
    hit = hits[0]
    assert hit["page_number"] == 2
    assert hit["document_title"] == body["document"]["title"]
    assert hit["version_number"] == 1 and hit["version_id"] == vid
    assert hit["snippet"].strip()
    assert "⟦earthing⟧" in hit["snippet"] and "<b>" not in hit["snippet"]


def test_progress_reaches_page_count(admin) -> None:
    tid = make_tender(admin)
    body = upload_and_ingest(admin, tid, make_pdf(["one", "two", "three"]))
    job = get_job(admin, str(body["job_id"]))
    assert job["progress_done"] == job["progress_total"] == 3


def test_reingesting_a_version_is_idempotent(admin) -> None:
    tid = make_tender(admin)
    body = upload_and_ingest(admin, tid, make_pdf(["first page text", "second page text"]))
    version_id = UUID(body["version"]["id"])
    ctx = OrgContext.system(UUID(admin.org_id), UUID(admin.me["user_id"]))

    def counts() -> tuple[int, list[int], list[int]]:
        with session_scope() as s:
            pages = s.scalars(
                select(DocumentPage.page_number).where(
                    DocumentPage.document_version_id == version_id
                )
            ).all()
            ordinals = s.scalars(
                select(DocumentChunk.ordinal)
                .where(DocumentChunk.document_version_id == version_id)
                .order_by(DocumentChunk.ordinal)
            ).all()
        return len(pages), sorted(pages), list(ordinals)

    before = counts()
    for _ in range(2):
        with session_scope() as s:
            result = knowledge.ingest_version(s, ctx, get_storage(), version_id)
        assert result.pages == 2
    after = counts()
    assert after == before
    assert after[0] == 2 and after[2] == list(range(len(after[2]))) and after[2]


def test_new_version_supersedes_old_in_search(admin) -> None:
    tid = make_tender(admin)
    v1 = upload_and_ingest(admin, tid, make_pdf(["alpha clause for cabling"]))
    did = v1["document"]["id"]
    v2 = admin.client.post(
        f"{API}/documents/{did}/versions",
        files={"file": ("tender.pdf", make_pdf(["beta clause for cabling"]), "application/pdf")},
    ).json()
    assert run_worker() is True

    def search(q: str) -> list[dict]:
        return admin.client.get(f"{API}/tenders/{tid}/search", params={"q": q}).json()

    assert search("alpha") == []
    beta = search("beta")
    assert beta and all(
        h["version_number"] == 2 and h["version_id"] == v2["version"]["id"] for h in beta
    )
    old = admin.client.get(f"{API}/document-versions/{v1['version']['id']}/pages/1").json()
    assert "alpha" in old["text"]


def test_corrupt_pdf_fails_permanently_and_can_be_retried(admin) -> None:
    tid = make_tender(admin)
    raw = b"%PDF-1.4 not really a pdf"
    body = upload_and_ingest(admin, tid, raw)
    job = get_job(admin, str(body["job_id"]))
    assert job["status"] == "failed" and job["error_code"] == "FILE_CORRUPT"
    vid, did = body["version"]["id"], body["document"]["id"]
    assert get_version(admin, did, vid)["processing_status"] == "failed"
    assert admin.client.get(f"{API}/document-versions/{vid}/file").content == raw
    assert run_worker() is False  # not requeued

    retry = admin.client.post(f"{API}/jobs/{body['job_id']}/retry")
    assert retry.status_code == 200
    fresh = retry.json()
    assert fresh["id"] != body["job_id"] and fresh["status"] == "queued"
    again = admin.client.post(f"{API}/jobs/{body['job_id']}/retry").json()
    assert again["id"] == fresh["id"]


def test_encrypted_pdf_fails_without_retry(admin) -> None:
    tid = make_tender(admin)
    body = upload_and_ingest(admin, tid, make_encrypted_pdf())
    job = get_job(admin, str(body["job_id"]))
    assert job["status"] == "failed" and job["error_code"] == "PDF_ENCRYPTED"
    assert job["attempt_count"] == 1
    assert run_worker() is False


def test_scanned_pdf_uses_ocr_and_is_searchable(admin, monkeypatch) -> None:
    use_ocr(monkeypatch, FakeOcr("Lightning protection schedule"))
    tid = make_tender(admin)
    body = upload_and_ingest(admin, tid, make_scanned_pdf(["ignored"]))
    vid, did = body["version"]["id"], body["document"]["id"]
    assert get_job(admin, str(body["job_id"]))["status"] == "succeeded"
    assert get_version(admin, did, vid)["processing_status"] == "ready"
    page = admin.client.get(f"{API}/document-versions/{vid}/pages/1").json()
    assert page["text_source"] == "ocr" and page["ocr_confidence"] == 90.0
    hits = admin.client.get(f"{API}/tenders/{tid}/search", params={"q": "lightning"}).json()
    assert hits and hits[0]["page_number"] == 1


def test_ocr_failure_gives_warnings(admin, monkeypatch) -> None:
    use_ocr(monkeypatch, FailingOcr())
    tid = make_tender(admin)
    body = upload_and_ingest(admin, tid, make_scanned_pdf(["a", "b"]))
    vid, did = body["version"]["id"], body["document"]["id"]
    job = get_job(admin, str(body["job_id"]))
    assert job["status"] == "succeeded_with_warnings"
    assert {"code": "OCR_FAILED", "pages": [1, 2]} in job["warnings"]
    assert get_version(admin, did, vid)["processing_status"] == "ready_with_warnings"
    pages = admin.client.get(f"{API}/document-versions/{vid}/pages").json()
    assert [p["status"] for p in pages] == ["ocr_failed", "ocr_failed"]


def test_low_confidence_ocr_gives_warning(admin, monkeypatch) -> None:
    use_ocr(monkeypatch, FakeOcr("Faint scanned text", 40.0))
    tid = make_tender(admin)
    body = upload_and_ingest(admin, tid, make_scanned_pdf(["x"]))
    job = get_job(admin, str(body["job_id"]))
    assert job["status"] == "succeeded_with_warnings"
    assert {"code": "OCR_LOW_CONFIDENCE", "pages": [1]} in job["warnings"]


def test_xlsx_ingest_records_sheet_tables_and_is_searchable(admin) -> None:
    tid = make_tender(admin)
    data = make_xlsx([["Item", "Qty"], ["Distribution board DB-7", 3]])
    body = upload_and_ingest(admin, tid, data, "boq.xlsx")
    vid = body["version"]["id"]
    assert get_job(admin, str(body["job_id"]))["status"] == "succeeded"
    page = admin.client.get(f"{API}/document-versions/{vid}/pages/1").json()
    assert page["tables"] and page["tables"][0]["kind"] == "sheet"
    hits = admin.client.get(f"{API}/tenders/{tid}/search", params={"q": "DB-7"}).json()
    assert hits and hits[0]["page_number"] == 1


def test_csv_and_docx_ingest_to_ready(admin) -> None:
    tid = make_tender(admin)
    csv = upload_and_ingest(admin, tid, make_csv([["Item", "Qty"], ["Socket", "4"]]), "list.csv")
    docx = upload_and_ingest(
        admin, tid, make_docx(["Scope of works"], [["Item", "Qty"], ["Light", "2"]]), "scope.docx"
    )
    for body in (csv, docx):
        assert get_job(admin, str(body["job_id"]))["status"] == "succeeded"
        v = get_version(admin, body["document"]["id"], body["version"]["id"])
        assert v["processing_status"] == "ready"


SECRET = "boom with secret text"
DOC_TEXT = "Confidential rewiring scope for the north wing"


def assert_logs_clean(caplog, *secrets: str) -> None:
    """Check everything a log handler could write: messages, and formatted tracebacks."""
    assert caplog.records
    for secret in secrets:
        assert secret not in caplog.text
    for record in caplog.records:
        assert record.exc_info is None and record.exc_text is None, record.getMessage()
        for secret in secrets:
            assert secret not in record.getMessage()


def patch_ingest(monkeypatch, exc: Exception) -> None:
    def raiser(*args, **kwargs):
        raise exc

    monkeypatch.setattr(knowledge, "ingest_version", raiser)


def test_unexpected_error_is_contained(admin, monkeypatch, caplog) -> None:
    tid = make_tender(admin)
    body = upload(admin, tid, make_pdf([DOC_TEXT])).json()
    patch_ingest(monkeypatch, RuntimeError(SECRET))
    with caplog.at_level(logging.DEBUG):
        assert run_worker() is True
    job = get_job(admin, str(body["job_id"]))
    assert job["status"] == "failed" and job["error_code"] == "UNEXPECTED"
    assert SECRET not in str(job)
    v = get_version(admin, body["document"]["id"], body["version"]["id"])
    assert v["processing_status"] == "failed"
    # Logging hygiene: nothing logged (messages, formatted tracebacks) carries the secret or text.
    assert_logs_clean(caplog, SECRET, DOC_TEXT)


def test_transient_failure_requeues_with_backoff(admin, monkeypatch) -> None:
    tid = make_tender(admin)
    body = upload(admin, tid, make_pdf(["text"])).json()
    patch_ingest(monkeypatch, ProcessingFailed("TEMP", transient=True))
    assert run_worker() is True
    job = get_job(admin, str(body["job_id"]))
    assert job["status"] == "queued" and job["attempt_count"] == 1
    with session_scope() as s:
        run_after = s.get(Job, UUID(body["job_id"])).run_after
    assert run_after > datetime.now(UTC)
    assert run_worker() is False  # backoff: not runnable yet
    v = get_version(admin, body["document"]["id"], body["version"]["id"])
    assert v["processing_status"] != "failed"  # it will be retried


def test_audit_events_never_hold_document_text(admin) -> None:
    tid = make_tender(admin)
    upload_and_ingest(admin, tid, make_pdf([DOC_TEXT]))
    with session_scope() as s:
        rows = s.scalars(select(AuditEvent.event_metadata)).all()
    assert rows
    assert "Confidential" not in str(rows) and "rewiring" not in str(rows)


def test_logs_hold_no_document_text_on_failed_parse(admin, caplog) -> None:
    tid = make_tender(admin)
    upload(admin, tid, b"%PDF-1.4 " + DOC_TEXT.encode())
    with caplog.at_level(logging.DEBUG):
        assert run_worker() is True
    assert_logs_clean(caplog, DOC_TEXT)


def test_database_rejection_does_not_leak_document_text_to_logs(admin, monkeypatch, caplog) -> None:
    """A database error on a statement holding document text must not put that text in the log."""
    from app.modules.knowledge import parsers
    from app.modules.knowledge import service as knowledge_service

    tid = make_tender(admin)
    body = upload(admin, tid, make_pdf(["anything"])).json()
    # label is varchar(200): the insert of this page (text included) is rejected by Postgres.
    page = parsers.ParsedPage(1, DOC_TEXT, label="L" * 300)
    monkeypatch.setattr(knowledge_service, "parse_document", lambda *a, **k: [page])
    with caplog.at_level(logging.DEBUG):
        assert run_worker() is True
    job = get_job(admin, str(body["job_id"]))
    assert job["status"] == "failed" and job["error_code"] == "UNEXPECTED"
    assert_logs_clean(caplog, DOC_TEXT)


def test_database_errors_do_not_embed_parameter_values() -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    # "value too long" does not echo the value itself, so only SQLAlchemy's [parameters: ...]
    # section could carry it.
    try:
        with session_scope() as s:
            s.execute(text("CREATE TEMP TABLE probe (v varchar(5))"))
            s.execute(text("INSERT INTO probe VALUES (:v)"), {"v": DOC_TEXT})
    except DBAPIError as exc:
        assert DOC_TEXT not in str(exc)
    else:
        raise AssertionError("the cast should have failed")


def test_csv_with_nul_bytes_ingests_with_them_removed(admin) -> None:
    tid = make_tender(admin)
    rows = [["Item", "Qty"]] + [[f"Socket outlet {i}", str(i)] for i in range(600)]
    head = make_csv(rows, delimiter=",", encoding="utf-8")
    assert len(head) > 8192  # the NUL sits after the part the upload sniff looks at
    data = head + b"\nNul\x00ified cable,7\n"
    body = upload_and_ingest(admin, tid, data, "boq.csv")
    assert get_job(admin, str(body["job_id"]))["status"] == "succeeded"
    vid, did = body["version"]["id"], body["document"]["id"]
    assert get_version(admin, did, vid)["processing_status"] == "ready"
    page = admin.client.get(f"{API}/document-versions/{vid}/pages/1").json()
    assert "\x00" not in page["text"] and "Nulified cable | 7" in page["text"]
    assert ["Nulified cable", "7"] in page["tables"][0]["rows"]


def test_reaped_job_fails_its_version(admin) -> None:
    """A worker that crashed on the last attempt: the reaper fails the job AND its version."""
    from datetime import timedelta

    from sqlalchemy import update

    from app.modules.jobs import public as jobs

    tid = make_tender(admin)
    body = upload(admin, tid, make_pdf(["text"])).json()
    with session_scope() as s:
        claimed = jobs.claim_next(s, 60)  # the worker took it, then died
    assert claimed and str(claimed.id) == body["job_id"]
    with session_scope() as s:
        s.execute(
            update(Job)
            .where(Job.id == claimed.id)
            .values(leased_until=datetime.now(UTC) - timedelta(seconds=1), attempt_count=3)
        )
    assert run_worker() is False  # nothing left to run
    job = get_job(admin, body["job_id"])
    assert job["status"] == "failed" and job["error_code"] == "LEASE_EXPIRED"
    v = get_version(admin, body["document"]["id"], body["version"]["id"])
    assert v["processing_status"] == "failed"


def test_processing_status_is_visible_while_ingest_runs(admin, monkeypatch) -> None:
    import threading

    from app.modules.knowledge import service as knowledge_service

    real_parse = knowledge_service.parse_document
    started, release = threading.Event(), threading.Event()

    def slow_parse(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(knowledge_service, "parse_document", slow_parse)
    tid = make_tender(admin)
    body = upload(admin, tid, make_pdf(["Slow tender text for the parser."])).json()
    did, vid = body["document"]["id"], body["version"]["id"]
    worker = threading.Thread(target=run_worker)
    worker.start()
    try:
        assert started.wait(10)
        seen = get_version(admin, did, vid)["processing_status"]  # another session
    finally:
        release.set()
        worker.join(10)
    assert seen == "processing"
    assert get_version(admin, did, vid)["processing_status"] == "ready"


def _transient_errors() -> list[Exception]:
    from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

    lost = Exception("server closed the connection unexpectedly")
    return [
        OperationalError("SELECT 1", {}, lost),
        InterfaceError("SELECT 1", {}, lost),
        DBAPIError("SELECT 1", {}, lost, connection_invalidated=True),
        OSError("storage volume unavailable"),
    ]


def test_infrastructure_errors_are_retried_with_backoff(admin, monkeypatch) -> None:
    tid = make_tender(admin)
    for exc in _transient_errors():
        body = upload(admin, tid, make_pdf(["text"])).json()
        patch_ingest(monkeypatch, exc)
        assert run_worker() is True
        job = get_job(admin, str(body["job_id"]))
        assert (job["status"], job["attempt_count"]) == ("queued", 1), type(exc).__name__
        assert job["error_code"] == "INFRASTRUCTURE"
        with session_scope() as s:
            run_after = s.get(Job, UUID(body["job_id"])).run_after
        assert run_after > datetime.now(UTC)
        v = get_version(admin, body["document"]["id"], body["version"]["id"])
        assert v["processing_status"] != "failed"


def test_other_errors_stay_permanent(admin, monkeypatch) -> None:
    from sqlalchemy.exc import DBAPIError

    tid = make_tender(admin)
    for exc in (RuntimeError("bug"), DBAPIError("SELECT 1", {}, Exception("constraint"))):
        body = upload(admin, tid, make_pdf(["text"])).json()
        patch_ingest(monkeypatch, exc)
        assert run_worker() is True
        job = get_job(admin, str(body["job_id"]))
        assert (job["status"], job["error_code"]) == ("failed", "UNEXPECTED")


def test_failed_completion_after_commit_does_not_fail_the_version(admin, monkeypatch) -> None:
    from sqlalchemy.exc import OperationalError

    from app.modules.jobs import public as jobs
    from app.worker import runner

    real_complete = jobs.complete
    calls = {"n": 0}

    def flaky_complete(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("UPDATE jobs", {}, Exception("connection lost"))
        return real_complete(*args, **kwargs)

    monkeypatch.setattr(jobs, "complete", flaky_complete)
    monkeypatch.setattr(runner, "COMPLETE_RETRY_DELAYS", (0, 0))
    tid = make_tender(admin)
    body = upload_and_ingest(admin, tid, make_pdf(["Pages and chunks are committed."]))
    v = get_version(admin, body["document"]["id"], body["version"]["id"])
    assert v["processing_status"] == "ready"
    assert get_job(admin, str(body["job_id"]))["status"] == "succeeded"
    assert calls["n"] == 2


def test_completion_that_keeps_failing_is_left_to_the_lease(admin, monkeypatch) -> None:
    from sqlalchemy.exc import OperationalError

    from app.modules.jobs import public as jobs
    from app.worker import runner

    def broken_complete(*args, **kwargs):
        raise OperationalError("UPDATE jobs", {}, Exception("connection lost"))

    monkeypatch.setattr(jobs, "complete", broken_complete)
    monkeypatch.setattr(runner, "COMPLETE_RETRY_DELAYS", (0, 0))
    tid = make_tender(admin)
    body = upload_and_ingest(admin, tid, make_pdf(["Pages and chunks are committed."]))
    v = get_version(admin, body["document"]["id"], body["version"]["id"])
    assert v["processing_status"] == "ready"
    assert get_job(admin, str(body["job_id"]))["status"] == "running"  # the lease reclaims it

    # Even if the reaper then fails the job (attempts used up), the committed version stays ready.
    from datetime import timedelta

    from sqlalchemy import update

    with session_scope() as s:
        s.execute(
            update(Job)
            .where(Job.id == UUID(body["job_id"]))
            .values(leased_until=datetime.now(UTC) - timedelta(seconds=1), attempt_count=3)
        )
    assert run_worker() is False
    assert get_job(admin, str(body["job_id"]))["error_code"] == "LEASE_EXPIRED"
    v = get_version(admin, body["document"]["id"], body["version"]["id"])
    assert v["processing_status"] == "ready"


def test_search_snippets_are_plain_text_with_markers(admin) -> None:
    """Snippets are raw document text: highlight markers, never HTML the client could render."""
    tid = make_tender(admin)
    upload_and_ingest(
        admin, tid, make_pdf(["Cable <script>alert(1)</script> tray <b>bold</b> install."])
    )
    r = admin.client.get(f"{API}/tenders/{tid}/search", params={"q": "cable"})
    assert r.headers["content-type"].startswith("application/json")
    (hit,) = r.json()
    assert "⟦Cable⟧" in hit["snippet"]
    assert "<b>" not in hit["snippet"] and "<script" not in hit["snippet"]
