from sqlalchemy import select

from app.config import get_settings
from app.db.session import session_scope
from app.modules.documents.models import DocumentVersion
from app.modules.documents.sniff import safe_filename, sniff
from tests.conftest import add_member, make_pdf, make_tender, make_xlsx, register, upload

SAMPLE_PDF = make_pdf(["3.1 Sealed tenders must be deposited before 11:00 on 27 November 2026."])


def test_upload_creates_a_pending_version_and_a_queued_job(admin) -> None:
    tid = make_tender(admin)
    r = upload(admin, tid, SAMPLE_PDF)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"]["version_number"] == 1 and body["version"]["is_current"] is True
    assert body["version"]["processing_status"] == "pending"
    assert body["version"]["file_format"] == "pdf" and len(body["version"]["checksum_sha256"]) == 64
    job = admin.client.get(f"/api/v1/jobs/{body['job_id']}").json()
    assert job["status"] == "queued" and job["job_type"] == "ingest_document"


def test_original_file_is_downloadable_unchanged_and_not_sniffable(admin) -> None:
    tid = make_tender(admin)
    version = upload(admin, tid, SAMPLE_PDF).json()["version"]
    r = admin.client.get(f"/api/v1/document-versions/{version['id']}/file")
    assert r.status_code == 200 and r.content == SAMPLE_PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("inline")
    xlsx = upload(admin, tid, make_xlsx([["a", "b"]]), "boq.xlsx", "boq").json()["version"]
    disposition = admin.client.get(f"/api/v1/document-versions/{xlsx['id']}/file").headers
    assert disposition["content-disposition"].startswith("attachment")


def test_content_must_match_the_extension(admin) -> None:
    tid = make_tender(admin)
    cases = {
        "empty.pdf": b"",
        "notes.txt": b"hello",
        "fake.pdf": b"MZ\x90\x00 this is an executable renamed to pdf",
        "wrong.xlsx": SAMPLE_PDF,
        "wrong.pdf": make_xlsx([["a"]]),
        "page.html": b"<html></html>",
    }
    for name, data in cases.items():
        r = upload(admin, tid, data, name)
        assert r.status_code == 422, f"{name} should be rejected"
        assert r.json()["error"]["code"] == "validation_error"


def test_oversize_files_are_rejected(admin, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    tid = make_tender(admin)
    big = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10)
    assert upload(admin, tid, big).status_code == 422


def test_unknown_kind_is_rejected(admin) -> None:
    tid = make_tender(admin)
    assert upload(admin, tid, SAMPLE_PDF, kind="virus").status_code == 422


def test_filenames_are_sanitised_and_cannot_escape_storage(admin) -> None:
    tid = make_tender(admin)
    r = upload(admin, tid, SAMPLE_PDF, "../../etc/passwd.pdf")
    assert r.status_code == 201
    vid = r.json()["version"]["id"]
    with session_scope() as s:
        v = s.scalar(select(DocumentVersion).where(DocumentVersion.id == vid))
    assert ".." not in v.storage_key and v.filename == "passwd.pdf"
    assert v.storage_key.startswith(f"org/{admin.org_id}/")
    assert safe_filename('a<b>"c|d.pdf') == "a_b__c_d.pdf"
    assert safe_filename("C:\\temp\\x.pdf") == "x.pdf" and safe_filename("") == "document"


def test_new_versions_replace_the_current_one(admin) -> None:
    tid = make_tender(admin)
    first = upload(admin, tid, SAMPLE_PDF).json()
    doc_id = first["document"]["id"]
    second = admin.client.post(
        f"/api/v1/documents/{doc_id}/versions",
        files={"file": ("tender_v2.pdf", make_pdf(["Updated tender text."]), "application/pdf")},
    )
    assert second.status_code == 201 and second.json()["version"]["version_number"] == 2
    versions = admin.client.get(f"/api/v1/documents/{doc_id}/versions").json()
    assert [(v["version_number"], v["is_current"]) for v in versions] == [(2, True), (1, False)]
    doc = admin.client.get(f"/api/v1/documents/{doc_id}").json()
    assert doc["current_version"]["version_number"] == 2
    listing = admin.client.get(f"/api/v1/tenders/{tid}/documents").json()
    assert len(listing) == 1 and listing[0]["current_version"]["version_number"] == 2


def test_roles_for_uploading(admin) -> None:
    tid = make_tender(admin)
    reviewer = add_member(admin, "rev@example.com", "reviewer")
    estimator = add_member(admin, "est@example.com", "estimator")
    manager = add_member(admin, "pm@example.com", "project_manager")
    assert upload(reviewer, tid, SAMPLE_PDF).status_code == 403
    assert upload(manager, tid, SAMPLE_PDF).status_code == 403
    assert upload(estimator, tid, SAMPLE_PDF).status_code == 201
    assert len(reviewer.client.get(f"/api/v1/tenders/{tid}/documents").json()) == 1


def test_archived_tenders_do_not_accept_uploads(admin) -> None:
    tid = make_tender(admin)
    admin.client.post(f"/api/v1/tenders/{tid}/archive")
    assert upload(admin, tid, SAMPLE_PDF).status_code == 409


def test_other_organisations_cannot_touch_documents(admin) -> None:
    tid = make_tender(admin)
    body = upload(admin, tid, SAMPLE_PDF).json()
    other = register("other@example.com", org="Other Co")
    vid, did = body["version"]["id"], body["document"]["id"]
    assert upload(other, tid, SAMPLE_PDF).status_code == 404
    assert other.client.get(f"/api/v1/tenders/{tid}/documents").status_code == 404
    assert other.client.get(f"/api/v1/documents/{did}").status_code == 404
    assert other.client.get(f"/api/v1/document-versions/{vid}/file").status_code == 404
    assert other.client.get(f"/api/v1/jobs/{body['job_id']}").status_code == 404


def test_sniffing_does_not_trust_names_or_partial_signatures() -> None:
    assert sniff(SAMPLE_PDF) == "pdf" and sniff(make_xlsx([["a"]])) == "xlsx"
    assert sniff(b"a,b,c\n1,2,3\n") == "csv"
    assert sniff(b"\x00\x01\x02binary") is None and sniff(b"") is None
    assert sniff(b"PK\x03\x04 not really a zip") is None
    assert sniff(b"just some prose without delimiters") is None
