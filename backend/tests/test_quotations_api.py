"""Quotations API: list (current versions), header patch, supplier switch with matches, roles."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.db.session import session_scope
from app.modules.audit.models import AuditEvent
from app.modules.estimating.models import BoqItem
from app.modules.suppliers.models import MatchSuggestion, Quotation, QuotationItem
from tests.conftest import Actor, add_member, make_tender, register
from tests.test_extraction_pipeline import API, drain
from tests.test_suppliers_api import PACK02, QUOTES, _matched_org


def _list(actor: Actor, tender_id: str) -> list[dict]:
    r = actor.client.get(f"{API}/tenders/{tender_id}/quotations")
    assert r.status_code == 200, r.text
    return r.json()


def _by_supplier(rows: list[dict]) -> dict[str, dict]:
    return {("spark" if "park" in r["supplier_name"] else "green"): r for r in rows}


def test_list_shows_both_quotations_with_supplier_names_and_counts() -> None:
    actor, tender_id = _matched_org("q1@example.com")
    rows = _list(actor, tender_id)
    assert len(rows) == 2
    assert [r["item_count"] for r in rows] == [15, 15]
    assert all(r["supplier_name"] for r in rows)
    assert set(rows[0]) == {
        "id", "document_version_id", "supplier_id", "supplier_name", "reference", "quote_date",
        "valid_until", "currency", "prices_include_vat", "flags", "item_count", "created_at",
    }  # fmt: skip
    green = _by_supplier(rows)["green"]
    assert "VAT_UNKNOWN" in green["flags"] and green["prices_include_vat"] is None


def test_only_current_versions_are_listed() -> None:
    actor, tender_id = _matched_org("q2@example.com")
    before = _by_supplier(_list(actor, tender_id))
    docs = actor.client.get(f"{API}/tenders/{tender_id}/documents").json()
    doc = next(
        d for d in docs if d["current_version"]["id"] == before["green"]["document_version_id"]
    )
    body = (PACK02 / QUOTES[1]).read_bytes()
    r = actor.client.post(
        f"{API}/documents/{doc['id']}/versions",
        files={"file": (QUOTES[1], body, "application/octet-stream")},
    )
    assert r.status_code == 201, r.text
    drain()
    after = _list(actor, tender_id)
    assert len(after) == 2
    green = _by_supplier(after)["green"]
    assert green["document_version_id"] == r.json()["version"]["id"]
    assert green["document_version_id"] != before["green"]["document_version_id"]


def test_the_list_needs_a_tender_of_your_organisation() -> None:
    actor, _ = _matched_org("q3@example.com")
    other = register("q3b@example.com", org="Other")
    assert other.client.get(f"{API}/tenders/{make_tender(actor)}/quotations").status_code == 404
    assert other.client.get(f"{API}/tenders/{uuid4()}/quotations").status_code == 404


def _patch(actor: Actor, quotation_id: str, body: dict):
    return actor.client.patch(f"{API}/quotations/{quotation_id}", json=body)


def test_patch_header_fields_and_flags_follow() -> None:
    actor, tender_id = _matched_org("q4@example.com")
    q = _by_supplier(_list(actor, tender_id))["spark"]
    r = _patch(actor, q["id"], {"reference": "Q-77", "quote_date": "2026-03-01",
                                "valid_until": "2026-02-01", "currency": "EUR",
                                "prices_include_vat": True})  # fmt: skip
    assert r.status_code == 200, r.text  # valid_until before quote_date is allowed
    body = r.json()
    assert (body["reference"], body["currency"], body["prices_include_vat"]) == (
        "Q-77",
        "EUR",
        True,
    )
    assert (body["quote_date"], body["valid_until"]) == ("2026-03-01", "2026-02-01")
    assert not {"NO_CURRENCY", "NO_REFERENCE", "VAT_UNKNOWN"} & set(body["flags"])
    cleared = _patch(actor, q["id"], {"currency": None}).json()
    assert "NO_CURRENCY" in cleared["flags"] and cleared["reference"] == "Q-77"
    assert cleared["item_count"] == 15 and cleared["supplier_name"] == q["supplier_name"]
    with session_scope() as s:
        events = s.scalars(select(AuditEvent).where(AuditEvent.action == "quotation_updated")).all()
        assert [e.event_metadata for e in events] == [
            {
                "fields": [
                    "currency",
                    "prices_include_vat",
                    "quote_date",
                    "reference",
                    "valid_until",
                ]
            },
            {"fields": ["currency"]},
        ]


def test_patch_validation() -> None:
    actor, tender_id = _matched_org("q5@example.com")
    q = _by_supplier(_list(actor, tender_id))["spark"]
    for body in ({}, {"currency": "zar"}, {"currency": "ZARR"}, {"supplier_id": None},
                 {"reference": "x" * 101}, {"reference": "a\x00b"}, {"quote_date": "not-a-date"},
                 {"bogus": 1}):  # fmt: skip
        assert _patch(actor, q["id"], body).status_code == 422, body
    assert _patch(actor, q["id"], {"currency": "ZAR"}).status_code == 200
    assert _patch(actor, str(uuid4()), {"currency": "ZAR"}).status_code == 404


def _match_suppliers() -> dict[UUID, UUID]:
    with session_scope() as s:
        return {m.id: m.supplier_id for m in s.scalars(select(MatchSuggestion))}


def test_switching_supplier_moves_the_quotation_and_its_matches() -> None:
    actor, tender_id = _matched_org("q6@example.com")
    rows = _by_supplier(_list(actor, tender_id))
    spark, green = rows["spark"], rows["green"]
    before = _match_suppliers()
    with session_scope() as s:
        spark_matches = {
            m.id
            for m in s.scalars(
                select(MatchSuggestion)
                .join(QuotationItem, QuotationItem.id == MatchSuggestion.quotation_item_id)
                .where(QuotationItem.quotation_id == UUID(spark["id"]))
            )
        }
    assert spark_matches
    r = _patch(actor, spark["id"], {"supplier_id": green["supplier_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["supplier_id"] == green["supplier_id"]
    assert r.json()["supplier_name"] == green["supplier_name"]
    after = _match_suppliers()
    assert set(after) == set(before)
    assert {after[m] for m in spark_matches} == {UUID(green["supplier_id"])}
    assert all(after[m] == before[m] for m in set(before) - spark_matches)
    counts = {s["id"]: s["quotation_count"] for s in actor.client.get(f"{API}/suppliers").json()}
    assert counts == {spark["supplier_id"]: 0, green["supplier_id"]: 2}


def test_unknown_or_foreign_supplier_is_404_and_changes_nothing() -> None:
    actor, tender_id = _matched_org("q7@example.com")
    spark = _by_supplier(_list(actor, tender_id))["spark"]
    other = register("q7b@example.com", org="Other")
    foreign = other.client.post(f"{API}/suppliers", json={"name": "Foreign"}).json()["id"]
    before = _match_suppliers()
    for sid in (foreign, str(uuid4())):
        assert _patch(actor, spark["id"], {"supplier_id": sid}).status_code == 404
    assert _match_suppliers() == before
    assert _by_supplier(_list(actor, tender_id))["spark"]["supplier_id"] == spark["supplier_id"]


def test_a_switch_that_would_double_confirm_a_line_is_a_conflict() -> None:
    actor, tender_id = _matched_org("q8@example.com")
    rows = _by_supplier(_list(actor, tender_id))
    with session_scope() as s:
        s.query(MatchSuggestion).delete()
        boq_id = s.scalars(select(BoqItem.id)).first()
        item = {
            k: s.scalars(select(QuotationItem.id).where(
                QuotationItem.quotation_id == UUID(rows[k]["id"]))).first()
            for k in rows
        }  # fmt: skip
        for k in rows:  # the same BoQ line confirmed for each supplier
            s.add(MatchSuggestion(
                organisation_id=UUID(actor.org_id), boq_item_id=boq_id, quotation_item_id=item[k],
                supplier_id=UUID(rows[k]["supplier_id"]), score=0.9, classification="clear",
                evidence={}, status="confirmed", decided_at=datetime.now(UTC),
                decided_by=UUID(actor.me["user_id"]),
            ))  # fmt: skip
    before = _match_suppliers()
    r = _patch(actor, rows["spark"]["id"], {"supplier_id": rows["green"]["supplier_id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "match_conflict", r.text
    assert _match_suppliers() == before
    assert (
        _by_supplier(_list(actor, tender_id))["spark"]["supplier_id"]
        == rows["spark"]["supplier_id"]
    )
    with session_scope() as s:
        assert s.get(Quotation, UUID(rows["spark"]["id"])).supplier_id == UUID(
            rows["spark"]["supplier_id"]
        )


def test_roles_and_archived_tender() -> None:
    actor, tender_id = _matched_org("q9@example.com")
    q = _by_supplier(_list(actor, tender_id))["spark"]
    for role in ("reviewer", "project_manager"):
        other = add_member(actor, f"{role}@example.com", role)
        assert _patch(other, q["id"], {"currency": "ZAR"}).status_code == 403
        assert len(_list(other, tender_id)) == 2
    estimator = add_member(actor, "est@example.com", "estimator")
    assert _patch(estimator, q["id"], {"currency": "EUR"}).status_code == 200
    assert actor.client.post(f"{API}/tenders/{tender_id}/archive").status_code in (200, 204)
    r = _patch(actor, q["id"], {"currency": "USD"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "tender_archived", r.text
    assert _by_supplier(_list(actor, tender_id))["spark"]["currency"] == "EUR"
    assert _patch(actor, str(uuid4()), {"currency": "USD"}).status_code == 404


def test_the_patch_takes_the_tender_lock(monkeypatch) -> None:
    from app.api.routers import quotations as router

    actor, tender_id = _matched_org("q10@example.com")
    q = _by_supplier(_list(actor, tender_id))["spark"]
    locked = []
    real = router.suppliers.lock_tender
    monkeypatch.setattr(
        router.suppliers, "lock_tender", lambda s, c, t: (locked.append(str(t)), real(s, c, t))[1]
    )
    assert _patch(actor, q["id"], {"currency": "ZAR"}).status_code == 200
    assert locked == [tender_id]
