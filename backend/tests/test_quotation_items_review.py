"""Quotation item review: list, correct, confirm, reject; validation; roles; matching trigger."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db.session import session_scope
from app.kernel import Conflict, OrgContext, Role
from app.modules.audit.models import AuditEvent
from app.modules.jobs.models import Job
from app.modules.suppliers import public as suppliers
from tests.conftest import add_member, make_tender, make_xlsx, register, upload
from tests.test_extraction_pipeline import API, drain

ROWS = [
    ["#", "Description", "Unit", "Qty", "Unit price"],
    ["1", "Cable 4mm", "m", "10", "5"],
    ["2", "Board 63 A", "each", "2", ""],
    ["3", "Conduit 20mm", "m", "1,500", "abc"],
]


def quote_version(actor=None, rows=None):
    """An organisation with an extracted XLSX quotation. Returns (actor, tender_id, version_id)."""
    actor = actor or register("qi@example.com")
    tender_id = make_tender(actor)
    body = upload(actor, tender_id, make_xlsx(rows or ROWS), "q.xlsx", kind="quotation").json()
    drain()
    return actor, tender_id, body["version"]["id"]


def items(actor, vid, **params) -> list[dict]:
    r = actor.client.get(f"{API}/document-versions/{vid}/quotation-items", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _item(actor, vid, description):
    return next(i for i in items(actor, vid) if i["description"] == description)


def _patch(actor, item_id, body):
    return actor.client.patch(f"{API}/quotation-items/{item_id}", json=body)


def _match_jobs(tender_id: str) -> int:
    with session_scope() as s:
        return s.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.job_type == "match_suppliers", Job.subject_id == UUID(tender_id))
        )


def test_listing_pages_in_source_order() -> None:
    admin, _, vid = quote_version()
    everything = items(admin, vid)
    assert [i["description"] for i in everything] == ["Cable 4mm", "Board 63 A", "Conduit 20mm"]
    assert {"unit_price", "raw_price", "sku", "reviewed_by_name", "quotation_id"} <= set(
        everything[0]
    )
    assert items(admin, vid, limit=2) == everything[:2]
    assert items(admin, vid, limit=2, offset=2) == everything[2:]
    assert (
        admin.client.get(
            f"{API}/document-versions/{vid}/quotation-items", params={"limit": 0}
        ).status_code
        == 422
    )
    assert (
        admin.client.get(
            f"{API}/document-versions/{vid}/quotation-items", params={"limit": 1001}
        ).status_code
        == 422
    )
    assert admin.client.get(f"{API}/document-versions/{uuid4()}/quotation-items").status_code == 404


def test_correcting_records_changes_and_keeps_the_original() -> None:
    admin, _, vid = quote_version()
    item = _item(admin, vid, "Cable 4mm")
    r = _patch(admin, item["id"], {"unit_price": "6.5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["unit_price"]) == Decimal("6.5") and body["review_status"] == "corrected"
    assert body["corrected_value"] == {"unit_price": "6.5"}
    assert Decimal(body["original_value"]["unit_price"]) == 5
    assert body["reviewed_by"] == admin.me["user_id"] and body["reviewed_at"]
    assert body["reviewed_by_name"] == admin.me["name"]
    again = _patch(admin, item["id"], {"description": "Cable 6mm", "sku": "C6"}).json()
    assert again["corrected_value"] == {
        "unit_price": "6.5", "description": "Cable 6mm", "sku": "C6",
    }  # fmt: skip
    assert again["original_value"] == body["original_value"]  # immutable snapshot


def test_confirm_reject_and_changing_your_mind() -> None:
    admin, _, vid = quote_version()
    item_id = _item(admin, vid, "Board 63 A")["id"]
    ok = admin.client.post(f"{API}/quotation-items/{item_id}/confirm").json()
    assert ok["review_status"] == "confirmed" and ok["corrected_value"] is None
    rej = admin.client.post(f"{API}/quotation-items/{item_id}/reject").json()
    assert rej["review_status"] == "rejected"
    fixed = _patch(admin, item_id, {"unit": "set"}).json()
    assert fixed["review_status"] == "corrected" and fixed["unit"] == "set"


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": 12.5},  # a JSON number, not text
        {"unit_price": 5},
        {"quantity": "1,500"},
        {"unit_price": "1.23456"},  # more than four decimals
        {"quantity": "1" * 15},
        {"unit_price": "-"},
        {},
        {"description": None},
        {"description": "   "},
        {"sku": "x" * 101},
        {"unit": "x" * 31},
        {"bogus": 1},
        {"unit_price": "0"},  # a zero price is not a price
    ],
)
def test_invalid_patches_are_rejected(body) -> None:
    admin, _, vid = quote_version()
    item = _item(admin, vid, "Cable 4mm")
    r = _patch(admin, item["id"], body)
    assert r.status_code == 422, r.text
    assert _item(admin, vid, "Cable 4mm")["review_status"] == "unreviewed"


@pytest.mark.parametrize("field", ["description", "sku", "unit"])
def test_a_nul_character_in_text_is_rejected(field) -> None:
    admin, _, vid = quote_version()
    item = _item(admin, vid, "Cable 4mm")
    assert _patch(admin, item["id"], {field: "Cab\x00le"}).status_code == 422


def test_correcting_figures_clears_their_flags() -> None:
    admin, _, vid = quote_version()
    unparsed = _item(admin, vid, "Conduit 20mm")
    assert {"price_unparsed", "ambiguous_separator"} <= set(unparsed["flags"])
    fixed = _patch(admin, unparsed["id"], {"unit_price": "8", "quantity": "1.5"}).json()
    assert Decimal(fixed["unit_price"]) == 8 and Decimal(fixed["quantity"]) == Decimal("1.5")
    assert not {"price_unparsed", "ambiguous_separator"} & set(fixed["flags"])
    missing = _item(admin, vid, "Board 63 A")
    assert "missing_price" in missing["flags"]
    priced = _patch(admin, missing["id"], {"unit_price": "99"}).json()
    assert "missing_price" not in priced["flags"]
    cleared = _patch(admin, missing["id"], {"unit_price": None}).json()
    assert cleared["unit_price"] is None and "missing_price" in cleared["flags"]
    no_qty = _patch(admin, missing["id"], {"quantity": None}).json()
    assert "missing_quantity" in no_qty["flags"]
    assert "missing_quantity" not in _patch(admin, missing["id"], {"quantity": "3"}).json()["flags"]


def test_an_unchanged_value_is_a_no_op() -> None:
    admin, tender_id, vid = quote_version()
    item = _item(admin, vid, "Cable 4mm")
    r = _patch(admin, item["id"], {"quantity": "10", "description": item["description"]})
    assert r.status_code == 200 and r.json()["review_status"] == "unreviewed"
    assert r.json()["reviewed_by"] is None


def test_edit_and_reject_queue_one_matching_job_and_confirm_none() -> None:
    admin, tender_id, vid = quote_version()
    a, b, c = (_item(admin, vid, d)["id"] for d in ("Cable 4mm", "Board 63 A", "Conduit 20mm"))
    before = _match_jobs(tender_id)
    assert admin.client.post(f"{API}/quotation-items/{a}/confirm").status_code == 200
    assert _match_jobs(tender_id) == before
    assert _patch(admin, a, {"unit_price": "7"}).status_code == 200
    assert _match_jobs(tender_id) == before + 1
    assert _patch(admin, b, {"unit": "box"}).status_code == 200  # the first job is still queued
    assert _match_jobs(tender_id) == before + 1
    drain()
    assert admin.client.post(f"{API}/quotation-items/{c}/reject").status_code == 200
    assert _match_jobs(tender_id) == before + 2


def test_only_admin_and_estimator_may_review() -> None:
    admin, _, vid = quote_version()
    item_id = _item(admin, vid, "Cable 4mm")["id"]
    for role in ("reviewer", "project_manager"):
        other = add_member(admin, f"{role}@example.com", role)
        assert _patch(other, item_id, {"unit": "m"}).status_code == 403
        assert other.client.post(f"{API}/quotation-items/{item_id}/confirm").status_code == 403
        assert other.client.post(f"{API}/quotation-items/{item_id}/reject").status_code == 403
        assert len(items(other, vid)) == 3
    estimator = add_member(admin, "estimator@example.com", "estimator", name="Esta Mator")
    assert estimator.client.post(f"{API}/quotation-items/{item_id}/confirm").status_code == 200
    reader = add_member(admin, "reader@example.com", "reviewer")
    assert _item(reader, vid, "Cable 4mm")["reviewed_by_name"] == "Esta Mator"


def test_an_unknown_id_is_a_404() -> None:
    admin, _, _ = quote_version()
    assert admin.client.post(f"{API}/quotation-items/{uuid4()}/confirm").status_code == 404
    assert _patch(admin, str(uuid4()), {"unit": "m"}).status_code == 404


def test_an_item_replaced_by_a_rerun_is_a_404_and_reviewed_rows_survive() -> None:
    admin, _, vid = quote_version()
    kept = _item(admin, vid, "Board 63 A")["id"]
    stale = _item(admin, vid, "Cable 4mm")["id"]
    admin.client.post(f"{API}/quotation-items/{kept}/confirm")
    admin.client.post(f"{API}/document-versions/{vid}/extract", json={"deep_scan": False})
    drain()
    after = items(admin, vid)
    assert len(after) == 3 and any(i["id"] == kept for i in after)
    assert _patch(admin, stale, {"unit": "m"}).status_code == 404


def test_an_archived_tender_refuses_review_writes() -> None:
    admin, tid, vid = quote_version()
    item_id = _item(admin, vid, "Cable 4mm")["id"]
    assert admin.client.post(f"{API}/tenders/{tid}/archive").status_code in (200, 204)
    jobs_before = _match_jobs(tid)
    for r in (
        _patch(admin, item_id, {"unit": "m"}),
        admin.client.post(f"{API}/quotation-items/{item_id}/confirm"),
        admin.client.post(f"{API}/quotation-items/{item_id}/reject"),
    ):
        assert r.status_code == 409 and r.json()["error"]["code"] == "tender_archived", r.text
    assert _item(admin, vid, "Cable 4mm")["review_status"] == "unreviewed"
    assert _match_jobs(tid) == jobs_before


def test_a_row_deleted_before_the_write_is_row_replaced() -> None:
    admin, _, _ = quote_version()
    ctx = OrgContext(UUID(admin.me["user_id"]), UUID(admin.org_id), Role.ADMIN)
    with session_scope() as s, pytest.raises(Conflict) as exc:
        suppliers.review_quotation_item(s, ctx, uuid4(), "confirm")
    assert exc.value.code == "row_replaced"


def test_review_writes_take_the_tender_and_extraction_locks(monkeypatch) -> None:
    from app.api.routers import quotations as router

    admin, tender_id, vid = quote_version()
    item_id = _item(admin, vid, "Cable 4mm")["id"]
    calls = []
    real_runs, real_tender = router.pipeline.lock_runs, router.suppliers.lock_tender

    def runs(session, ctx, version_id, kind):
        calls.append(("runs", str(version_id), kind))
        return real_runs(session, ctx, version_id, kind)

    def tender(session, ctx, tid):
        calls.append(("tender", str(tid)))
        return real_tender(session, ctx, tid)

    monkeypatch.setattr(router.pipeline, "lock_runs", runs)
    monkeypatch.setattr(router.suppliers, "lock_tender", tender)
    admin.client.post(f"{API}/quotation-items/{item_id}/confirm")
    assert calls == [("tender", tender_id), ("runs", vid, "quotation")]  # tender first


def test_review_is_audited_with_field_names_only() -> None:
    admin, _, vid = quote_version()
    item_id = _item(admin, vid, "Cable 4mm")["id"]
    _patch(admin, item_id, {"description": "Secret cable text"})
    with session_scope() as s:
        event = s.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "quotation_item")
        ).one()
    assert event.action == "review_corrected"
    assert event.event_metadata == {"status": "corrected", "fields": ["description"]}
    assert "Secret" not in str(event.event_metadata)
