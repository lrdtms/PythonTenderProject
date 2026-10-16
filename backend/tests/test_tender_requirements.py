"""Tender-wide requirements: current versions only, filters, paging, tenancy."""

from __future__ import annotations

from tests.conftest import make_pdf, make_tender, register
from tests.review_helpers import requirement_version, requirements
from tests.test_extraction_pipeline import API, drain, req_json

CLAUSE_2 = "Tenderers must attend the compulsory site meeting on Friday."


def test_lists_current_versions_only_and_filters(fake_llm) -> None:
    admin, tid, vid = requirement_version(fake_llm)
    url = f"{API}/tenders/{tid}/requirements"
    rows = admin.client.get(url).json()
    assert [r["document_version_id"] for r in rows] == [vid]

    doc_id = admin.client.get(f"{API}/tenders/{tid}/documents").json()[0]["id"]
    fake_llm([req_json(CLAUSE_2, "meeting")])
    new = admin.client.post(
        f"{API}/documents/{doc_id}/versions",
        files={"file": ("t2.pdf", make_pdf([CLAUSE_2]), "application/pdf")},
    )
    assert new.status_code == 201, new.text
    drain()
    rows = admin.client.get(url).json()
    assert len(rows) == 1 and rows[0]["document_version_id"] == new.json()["version"]["id"]
    assert rows[0]["requirement_type"] == "meeting"

    assert admin.client.get(url, params={"requirement_type": "meeting"}).json() == rows
    assert admin.client.get(url, params={"requirement_type": "deadline"}).json() == []
    assert admin.client.get(url, params={"review_status": "confirmed"}).json() == []
    assert admin.client.get(url, params={"requirement_type": "bogus"}).status_code == 422
    assert admin.client.get(url, params={"limit": 0}).status_code == 422


def test_a_tender_with_no_documents_is_an_empty_list() -> None:
    admin = register("empty@example.com")
    tid = make_tender(admin)
    assert admin.client.get(f"{API}/tenders/{tid}/requirements").json() == []


def test_requirements_helper_matches_version_list(fake_llm) -> None:
    admin, tid, vid = requirement_version(fake_llm)
    assert admin.client.get(f"{API}/tenders/{tid}/requirements").json() == requirements(admin, vid)
