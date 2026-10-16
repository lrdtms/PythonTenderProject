"""Extraction endpoints: permissions, preconditions, status shape, pagination."""

from __future__ import annotations

from tests.conftest import add_member, make_pdf, make_tender, register, upload
from tests.test_extraction_pipeline import API, drain

CLAUSE = "Tenderers must submit a valid tax clearance certificate."


def _ready(fake_llm=None):
    admin = register("api@example.com")
    tid = make_tender(admin)
    body = upload(admin, tid, make_pdf([CLAUSE]), "t.pdf").json()
    return admin, tid, body["version"]["id"], body


def test_extract_requires_review_permission(fake_llm) -> None:
    admin, _, vid, _ = _ready()
    drain()
    reviewer = add_member(admin, "rev@example.com", "reviewer")
    r = reviewer.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    assert r.status_code == 403
    assert reviewer.client.get(f"{API}/document-versions/{vid}/extraction").status_code == 200


def test_extract_before_ingest_finishes_is_a_conflict() -> None:
    admin, _, vid, _ = _ready()  # ingest not run yet: the version is `pending`
    r = admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    assert r.status_code == 409


def test_extract_returns_jobs_and_is_idempotent_while_active(fake_llm) -> None:
    admin, _, vid, _ = _ready()
    drain()
    first = admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    again = admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    assert first.status_code == again.status_code == 202
    assert {j["id"] for j in first.json()} == {j["id"] for j in again.json()}
    assert {j["job_type"] for j in first.json()} == {"extract_boq", "extract_requirements"}


def test_a_different_deep_scan_while_active_is_a_conflict(fake_llm) -> None:
    admin, _, vid, _ = _ready()
    drain()
    admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    r = admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": True})
    assert r.status_code == 409


def test_deep_scan_reaches_the_run(fake_llm) -> None:
    admin, _, vid, _ = _ready()
    drain()
    admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": True})
    drain()
    kinds = {
        k["kind"]: k
        for k in admin.client.get(f"{API}/document-versions/{vid}/extraction").json()["kinds"]
    }
    assert kinds["requirements"]["run"]["deep_scan"] is True
    assert kinds["requirements"]["job"]["status"] in ("succeeded", "succeeded_with_warnings")


def test_status_before_any_run_shows_queued_jobs(fake_llm) -> None:
    admin, _, vid, _ = _ready()
    from app.worker import handlers
    from app.worker.runner import process_one

    process_one(handlers.HANDLERS)  # ingest only; the extract jobs are queued
    kinds = {
        k["kind"]: k
        for k in admin.client.get(f"{API}/document-versions/{vid}/extraction").json()["kinds"]
    }
    assert kinds["boq"]["run"] is None and kinds["boq"]["job"]["status"] == "queued"


def test_lists_are_paginated(fake_llm) -> None:
    import json

    quotes = [f"Tenderers must submit form {i}." for i in range(3)]
    reply = json.dumps({"requirements": [
        {"description": f"d{i}", "requirement_type": "document", "mandatory_status": "mandatory",
         "evidence_quote": q} for i, q in enumerate(quotes)]})  # fmt: skip
    fake_llm([reply])
    admin = register("page@example.com")
    body = upload(admin, make_tender(admin), make_pdf([" ".join(quotes)]), "t.pdf").json()
    vid = body["version"]["id"]
    drain()
    url = f"{API}/document-versions/{vid}/requirements"
    assert len(admin.client.get(url).json()) == 3
    assert len(admin.client.get(url, params={"limit": 2}).json()) == 2
    assert len(admin.client.get(url, params={"limit": 2, "offset": 2}).json()) == 1
    assert admin.client.get(url, params={"limit": 0}).status_code in (200, 422)
