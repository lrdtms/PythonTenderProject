"""Requirement review: same rules as BoQ review, different fields."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.conftest import add_member
from tests.review_helpers import requirement_version, requirements
from tests.test_extraction_pipeline import API, drain


def _patch(actor, row_id, body):
    return actor.client.patch(f"{API}/requirements/{row_id}", json=body)


def test_correcting_a_requirement_keeps_the_original(fake_llm) -> None:
    admin, _, vid = requirement_version(fake_llm)
    row = requirements(admin, vid)[0]
    r = _patch(admin, row["id"], {"requirement_type": "deadline", "description": "Tax clearance"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requirement_type"] == "deadline" and body["review_status"] == "corrected"
    assert body["corrected_value"] == {"requirement_type": "deadline"}  # description unchanged
    assert body["original_value"]["requirement_type"] == "document"
    assert body["reviewed_by_name"] == admin.me["name"]
    assert body["evidence_quote"] == row["evidence_quote"]  # the quote is not editable


@pytest.mark.parametrize(
    "body",
    [
        {"requirement_type": "bogus"},
        {"mandatory_status": "maybe"},
        {"description": ""},
        {"description": None},
        {},
        {"evidence_quote": "rewritten"},
    ],
)
def test_invalid_requirement_patches_are_rejected(fake_llm, body) -> None:
    admin, _, vid = requirement_version(fake_llm)
    assert _patch(admin, requirements(admin, vid)[0]["id"], body).status_code == 422


def test_confirm_reject_and_roles(fake_llm) -> None:
    admin, _, vid = requirement_version(fake_llm)
    row_id = requirements(admin, vid)[0]["id"]
    assert (
        admin.client.post(f"{API}/requirements/{row_id}/reject").json()["review_status"]
        == "rejected"
    )
    assert (
        admin.client.post(f"{API}/requirements/{row_id}/confirm").json()["review_status"]
        == "confirmed"
    )
    for role in ("reviewer", "project_manager"):
        other = add_member(admin, f"{role}@example.com", role)
        assert other.client.post(f"{API}/requirements/{row_id}/confirm").status_code == 403
        assert _patch(other, row_id, {"mandatory_status": "informational"}).status_code == 403
    estimator = add_member(admin, "est2@example.com", "estimator")
    assert _patch(estimator, row_id, {"mandatory_status": "informational"}).status_code == 200


def test_an_archived_tender_refuses_requirement_review(fake_llm) -> None:
    admin, tid, vid = requirement_version(fake_llm)
    row_id = requirements(admin, vid)[0]["id"]
    assert admin.client.post(f"{API}/tenders/{tid}/archive").status_code in (200, 204)
    for r in (
        _patch(admin, row_id, {"mandatory_status": "informational"}),
        admin.client.post(f"{API}/requirements/{row_id}/confirm"),
        admin.client.post(f"{API}/requirements/{row_id}/reject"),
    ):
        assert r.status_code == 409 and r.json()["error"]["code"] == "tender_archived", r.text
    assert requirements(admin, vid)[0]["review_status"] == "unreviewed"


def test_a_reviewed_requirement_survives_a_rerun_and_stale_ids_are_404(fake_llm) -> None:
    admin, _, vid = requirement_version(fake_llm)
    row_id = requirements(admin, vid)[0]["id"]
    admin.client.post(f"{API}/requirements/{row_id}/confirm")
    admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    drain()
    rows = requirements(admin, vid)
    assert [r["id"] for r in rows] == [row_id] and rows[0]["review_status"] == "confirmed"
    assert admin.client.post(f"{API}/requirements/{uuid4()}/confirm").status_code == 404
