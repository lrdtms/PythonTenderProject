"""BoQ review: correct, confirm, reject; validation; roles; re-runs; audit."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.session import session_scope
from app.kernel import Conflict, OrgContext, Role
from app.modules.audit.models import AuditEvent
from app.modules.estimating import public as estimating
from tests.conftest import add_member
from tests.review_helpers import boq_items, boq_version
from tests.test_extraction_pipeline import API, drain


def _item(actor, vid, number):
    return next(i for i in boq_items(actor, vid) if i["item_no"] == number)


def _patch(actor, item_id, body):
    return actor.client.patch(f"{API}/boq-items/{item_id}", json=body)


def test_correcting_a_quantity_updates_the_value_and_keeps_the_original() -> None:
    admin, _, vid = boq_version()
    item = _item(admin, vid, "1.1")
    r = _patch(admin, item["id"], {"quantity": "12.5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["quantity"]) == Decimal("12.5") and body["review_status"] == "corrected"
    assert body["corrected_value"] == {"quantity": "12.5"}
    assert Decimal(body["original_value"]["quantity"]) == 10
    assert body["reviewed_by"] == admin.me["user_id"] and body["reviewed_at"]
    assert body["reviewed_by_name"] == admin.me["name"]

    again = _patch(admin, item["id"], {"description": "Cable 6mm"}).json()
    assert again["corrected_value"] == {"quantity": "12.5", "description": "Cable 6mm"}
    assert again["original_value"] == body["original_value"]  # immutable snapshot


def test_confirm_reject_and_changing_your_mind() -> None:
    admin, _, vid = boq_version()
    item_id = _item(admin, vid, "1.2")["id"]
    ok = admin.client.post(f"{API}/boq-items/{item_id}/confirm").json()
    assert ok["review_status"] == "confirmed" and ok["corrected_value"] is None
    assert (
        admin.client.post(f"{API}/boq-items/{item_id}/reject").json()["review_status"] == "rejected"
    )
    assert (
        admin.client.post(f"{API}/boq-items/{item_id}/confirm").json()["review_status"]
        == "confirmed"
    )
    fixed = _patch(admin, item_id, {"unit": "set"}).json()
    assert fixed["review_status"] == "corrected" and fixed["unit"] == "set"


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": 12.5},  # a JSON number, not text
        {"quantity": "1e3"},
        {"quantity": "1.23456"},  # more than four decimals
        {"quantity": "1" * 15},  # overflows NUMERIC(18,4)
        {"quantity": "abc"},
        {"rate": "-"},
        {},  # nothing to change
        {"description": None},  # cannot be cleared
        {"description": "   "},
        {"bogus": 1},  # unknown field
    ],
)
def test_invalid_patches_are_rejected(body) -> None:
    admin, _, vid = boq_version()
    item = _item(admin, vid, "1.1")
    r = _patch(admin, item["id"], body)
    assert r.status_code == 422, r.text
    assert _item(admin, vid, "1.1")["review_status"] == "unreviewed"  # nothing was written


@pytest.mark.parametrize("field", ["description", "section", "item_no", "unit"])
def test_a_nul_character_in_text_is_rejected(field) -> None:
    admin, _, vid = boq_version()
    item = _item(admin, vid, "1.1")
    r = _patch(admin, item["id"], {field: "Cable\x00 4mm"})
    assert r.status_code == 422, r.text
    assert _item(admin, vid, "1.1")["review_status"] == "unreviewed"


FLAG_ROWS = [
    ["Item", "Description", "Unit", "Quantity", "Rate", "Amount"],
    ["1.1", "Cable 4mm", "Metre", "1,500", "5", ""],
    ["1.2", "Lamp", "each", "rate only", "", ""],
]


def test_clearing_a_rate_only_quantity_does_not_add_missing_quantity() -> None:
    admin, _, vid = boq_version(rows=FLAG_ROWS)
    item = _item(admin, vid, "1.2")
    assert "rate_only" in item["flags"] and "missing_quantity" not in item["flags"]
    _patch(admin, item["id"], {"quantity": "3"})
    cleared = _patch(admin, item["id"], {"quantity": None}).json()
    assert cleared["quantity"] is None and "missing_quantity" not in cleared["flags"]
    assert "rate_only" in cleared["flags"]


def test_correcting_the_quantity_drops_the_ambiguous_separator_flag() -> None:
    admin, _, vid = boq_version(rows=FLAG_ROWS)
    item = _item(admin, vid, "1.1")
    assert "ambiguous_separator" in item["flags"]
    fixed = _patch(admin, item["id"], {"quantity": "1.5"}).json()
    assert Decimal(fixed["quantity"]) == Decimal("1.5")
    assert "ambiguous_separator" not in fixed["flags"]


def test_an_unchanged_value_is_a_no_op() -> None:
    admin, _, vid = boq_version()
    item = _item(admin, vid, "1.1")
    r = _patch(admin, item["id"], {"quantity": "10", "description": item["description"]})
    assert r.status_code == 200 and r.json()["review_status"] == "unreviewed"
    assert r.json()["reviewed_by"] is None


def test_adding_a_quantity_clears_the_missing_flag_and_clearing_it_restores_it() -> None:
    admin, _, vid = boq_version()
    item = _item(admin, vid, "1.3")
    assert "missing_quantity" in item["flags"] and item["quantity"] is None
    filled = _patch(admin, item["id"], {"quantity": "4"}).json()
    assert "missing_quantity" not in filled["flags"] and Decimal(filled["quantity"]) == 4
    cleared = _patch(admin, item["id"], {"quantity": None}).json()
    assert cleared["quantity"] is None and "missing_quantity" in cleared["flags"]


def test_only_admin_and_estimator_may_review() -> None:
    admin, _, vid = boq_version()
    item_id = _item(admin, vid, "1.1")["id"]
    for role in ("reviewer", "project_manager"):
        other = add_member(admin, f"{role}@example.com", role)
        assert _patch(other, item_id, {"unit": "m"}).status_code == 403
        assert other.client.post(f"{API}/boq-items/{item_id}/confirm").status_code == 403
        assert other.client.post(f"{API}/boq-items/{item_id}/reject").status_code == 403
        assert other.client.get(f"{API}/document-versions/{vid}/boq-items").status_code == 200
    estimator = add_member(admin, "estimator@example.com", "estimator", name="Esta Mator")
    assert estimator.client.post(f"{API}/boq-items/{item_id}/confirm").status_code == 200
    reader = add_member(admin, "reader@example.com", "reviewer")
    seen = _item(reader, vid, "1.1")
    assert seen["reviewed_by_name"] == "Esta Mator"  # a reader can see who reviewed


def test_an_id_replaced_by_a_rerun_is_a_404_and_reviewed_rows_survive() -> None:
    admin, _, vid = boq_version()
    kept = _item(admin, vid, "1.2")["id"]
    stale = _item(admin, vid, "1.1")["id"]
    admin.client.post(f"{API}/boq-items/{kept}/confirm")
    admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    drain()
    after = boq_items(admin, vid)
    assert len(after) == 3 and any(i["id"] == kept for i in after)
    assert _patch(admin, stale, {"unit": "m"}).status_code == 404
    assert admin.client.post(f"{API}/boq-items/{uuid4()}/confirm").status_code == 404


def test_an_archived_tender_refuses_review_writes() -> None:
    admin, tid, vid = boq_version()
    item_id = _item(admin, vid, "1.1")["id"]
    assert admin.client.post(f"{API}/tenders/{tid}/archive").status_code in (200, 204)
    for r in (
        _patch(admin, item_id, {"unit": "m"}),
        admin.client.post(f"{API}/boq-items/{item_id}/confirm"),
        admin.client.post(f"{API}/boq-items/{item_id}/reject"),
    ):
        assert r.status_code == 409 and r.json()["error"]["code"] == "tender_archived", r.text
    assert _item(admin, vid, "1.1")["review_status"] == "unreviewed"
    assert admin.client.post(f"{API}/boq-items/{uuid4()}/confirm").status_code == 404


def test_a_row_deleted_before_the_write_is_row_replaced() -> None:
    admin, _, _ = boq_version()
    ctx = OrgContext(UUID(admin.me["user_id"]), UUID(admin.org_id), Role.ADMIN)
    with session_scope() as s, pytest.raises(Conflict) as exc:
        estimating.review_item(s, ctx, uuid4(), "confirm")
    assert exc.value.code == "row_replaced"


def test_review_writes_take_the_extraction_lock(monkeypatch) -> None:
    from app.api.routers import review

    admin, _, vid = boq_version()
    item_id = _item(admin, vid, "1.1")["id"]
    calls = []
    real = review.pipeline.lock_runs

    def spy(session, ctx, version_id, kind):
        calls.append((str(version_id), kind))
        return real(session, ctx, version_id, kind)

    monkeypatch.setattr(review.pipeline, "lock_runs", spy)
    admin.client.post(f"{API}/boq-items/{item_id}/confirm")
    assert calls == [(vid, "boq")]


def test_review_is_audited_with_field_names_only() -> None:
    admin, _, vid = boq_version()
    item_id = _item(admin, vid, "1.1")["id"]
    _patch(admin, item_id, {"description": "Secret cable text"})
    with session_scope() as s:
        event = s.scalars(select(AuditEvent).where(AuditEvent.entity_type == "boq_item")).one()
    assert event.action == "review_corrected"
    assert event.event_metadata == {"status": "corrected", "fields": ["description"]}
    assert "Secret" not in str(event.event_metadata)
