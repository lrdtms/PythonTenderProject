"""Match suggestions API: grouped list, decisions, confirm-clear, re-match trigger, roles."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.api.main import app
from app.db.session import session_scope
from app.modules.audit.models import AuditEvent
from app.modules.jobs.models import Job
from app.modules.suppliers.models import MatchSuggestion, Quotation, QuotationItem
from tests.conftest import Actor, add_member
from tests.test_extraction_pipeline import API, drain
from tests.test_suppliers_api import PACK02, QUOTES, _matched_org

BOQ_LINES = 20


def _get(actor: Actor, tender_id: str, **params) -> list[dict]:
    r = actor.client.get(f"{API}/tenders/{tender_id}/match-suggestions", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _flat(lines: list[dict]) -> list[dict]:
    return [s for line in lines for s in line["suggestions"]]


def _decide(actor: Actor, suggestion_id: str, action: str):
    return actor.client.post(f"{API}/match-suggestions/{suggestion_id}/{action}")


def _first(lines: list[dict], classification: str) -> dict:
    return next(s for s in _flat(lines) if s["classification"] == classification)


def test_one_line_per_current_boq_line_with_suggestions_attached() -> None:
    actor, tender_id = _matched_org("ma1@example.com")
    lines = _get(actor, tender_id, limit=500)
    assert len(lines) == BOQ_LINES
    assert any(not line["suggestions"] for line in lines), "some lines have no match"
    assert set(lines[0]["boq"]) == {
        "id", "item_no", "section", "description", "unit", "quantity",
    }  # fmt: skip
    sug = _flat(lines)
    assert sug
    one = sug[0]
    assert set(one) == {
        "id", "status", "classification", "rank", "score", "evidence", "supplier",
        "quotation_item", "boq_item_id", "decided_by", "decided_by_name", "decided_at",
    }  # fmt: skip
    assert set(one["supplier"]) == {"id", "name"}
    assert set(one["quotation_item"]) == {
        "id", "quotation_id", "description", "sku", "unit", "quantity", "unit_price",
        "valid_until",
    }  # fmt: skip
    assert all(
        isinstance(s["quotation_item"]["unit_price"], str)
        for s in sug
        if s["quotation_item"]["unit_price"]
    )
    assert all("warnings" in s["evidence"] and s["rank"] >= 1 for s in sug)
    assert all(s["status"] == "suggested" and s["decided_by"] is None for s in sug)
    for line in lines:
        assert all(s["boq_item_id"] == line["boq"]["id"] for s in line["suggestions"])


def test_filters_and_paging() -> None:
    actor, tender_id = _matched_org("ma2@example.com")
    everything = _get(actor, tender_id, limit=500)
    clear = _get(actor, tender_id, classification="clear", limit=500)
    assert len(clear) == BOQ_LINES
    assert {s["classification"] for s in _flat(clear)} == {"clear"}
    assert len(_flat(clear)) == sum(1 for s in _flat(everything) if s["classification"] == "clear")
    only = _get(actor, tender_id, only_with_suggestions="true", limit=500)
    assert 0 < len(only) < BOQ_LINES and all(line["suggestions"] for line in only)
    supplier = _flat(everything)[0]["supplier"]["id"]
    by_supplier = _flat(_get(actor, tender_id, supplier_id=supplier, limit=500))
    assert by_supplier and {s["supplier"]["id"] for s in by_supplier} == {supplier}
    assert _flat(_get(actor, tender_id, status="confirmed", limit=500)) == []
    assert len(_flat(_get(actor, tender_id, status="suggested", limit=500))) == len(
        _flat(everything)
    )
    page = _get(actor, tender_id, limit=5, offset=5)
    assert [x["boq"]["id"] for x in page] == [x["boq"]["id"] for x in everything[5:10]]
    assert _get(actor, tender_id, limit=5, offset=BOQ_LINES) == []
    for bad in ({"limit": 0}, {"limit": 501}, {"offset": -1}, {"status": "bogus"},
                {"classification": "bogus"}, {"supplier_id": "nope"}):  # fmt: skip
        r = actor.client.get(f"{API}/tenders/{tender_id}/match-suggestions", params=bad)
        assert r.status_code == 422, bad


def test_nothing_sorts_or_filters_by_price_and_order_is_supplier_then_rank() -> None:
    schema = app.openapi()
    for path, ops in schema["paths"].items():
        if "match" not in path:
            continue
        for op in ops.values():
            names = {p["name"].lower() for p in op.get("parameters", [])}
            assert not any(w in n for n in names for w in ("price", "sort", "order", "cost")), path
    actor, tender_id = _matched_org("ma3@example.com")
    lines = _get(actor, tender_id, limit=500)
    prices = set()
    multi = 0
    for line in lines:
        sug = line["suggestions"]
        keys = [(s["supplier"]["name"].lower(), s["rank"]) for s in sug]
        assert keys == sorted(keys), line["boq"]["description"]
        prices |= {s["quotation_item"]["unit_price"] for s in sug}
        multi += len({s["supplier"]["id"] for s in sug}) > 1
    assert len(prices) > 5 and multi, "the fixture must have different prices from two suppliers"


def test_confirm_reject_reset_and_decider_name() -> None:
    actor, tender_id = _matched_org("ma4@example.com")
    s = _first(_get(actor, tender_id, limit=500), "clear")
    r = _decide(actor, s["id"], "confirm")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "confirmed" and body["decided_by_name"] == "Owner"
    assert body["decided_by"] == actor.me["user_id"] and body["decided_at"]
    assert body["supplier"] == s["supplier"] and body["boq_item_id"] == s["boq_item_id"]
    listed = next(x for x in _flat(_get(actor, tender_id, limit=500)) if x["id"] == s["id"])
    assert listed["status"] == "confirmed" and listed["decided_by_name"] == "Owner"
    again = _decide(actor, s["id"], "confirm")  # repeating changes nothing
    assert again.status_code == 200 and again.json()["decided_at"] == body["decided_at"]
    rejected = _decide(actor, s["id"], "reject").json()
    assert rejected["status"] == "rejected" and rejected["decided_by_name"] == "Owner"
    reset = _decide(actor, s["id"], "reset").json()
    assert reset["status"] == "suggested"
    assert (reset["decided_by"], reset["decided_by_name"], reset["decided_at"]) == (None,) * 3
    assert _decide(actor, s["id"], "confirm").json()["status"] == "confirmed"
    with session_scope() as db:
        actions = [e.action for e in db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "match_suggestion")
            .order_by(AuditEvent.created_at))]  # fmt: skip
        assert actions == [
            "match_confirmed",
            "match_rejected",
            "match_reset",
            "match_confirmed",
        ]  # the repeated confirm wrote nothing
        meta = db.scalars(select(AuditEvent).where(AuditEvent.action == "match_reset")).one()
        assert meta.event_metadata == {"status": "suggested"} and meta.entity_id is not None
    assert _decide(actor, str(uuid4()), "confirm").status_code == 404


def _two_candidates(actor: Actor, tender_id: str) -> tuple[str, str]:
    """Two suggestions for the same BoQ line and supplier (creates one when the fixture has none)."""
    lines = _get(actor, tender_id, limit=500)
    for line in lines:
        by_supplier: dict[str, list[str]] = {}
        for s in line["suggestions"]:
            by_supplier.setdefault(s["supplier"]["id"], []).append(s["id"])
        pair = next((ids for ids in by_supplier.values() if len(ids) >= 2), None)
        if pair:
            return pair[0], pair[1]
    s = _flat(lines)[0]
    with session_scope() as db:
        item = db.get(QuotationItem, UUID(s["quotation_item"]["id"]))
        other = db.scalars(
            select(QuotationItem).where(
                QuotationItem.quotation_id == item.quotation_id, QuotationItem.id != item.id
            )
        ).first()
        extra = MatchSuggestion(
            organisation_id=item.organisation_id, boq_item_id=UUID(s["boq_item_id"]),
            quotation_item_id=other.id, supplier_id=UUID(s["supplier"]["id"]), score=0.5,
            classification="ambiguous", evidence={"rank": 9, "warnings": []},
        )  # fmt: skip
        db.add(extra)
        db.flush()
        return s["id"], str(extra.id)


def test_second_confirm_for_the_same_line_and_supplier_is_a_conflict() -> None:
    actor, tender_id = _matched_org("ma5@example.com")
    first, second = _two_candidates(actor, tender_id)
    assert _decide(actor, first, "confirm").status_code == 200
    r = _decide(actor, second, "confirm")
    assert r.status_code == 409 and r.json()["error"]["code"] == "match_conflict", r.text
    statuses = {s["id"]: s["status"] for s in _flat(_get(actor, tender_id, limit=500))}
    assert (statuses[first], statuses[second]) == ("confirmed", "suggested")
    assert _decide(actor, first, "reject").status_code == 200  # frees the slot
    assert _decide(actor, second, "confirm").status_code == 200


def test_an_ambiguous_suggestion_is_confirmed_one_by_one() -> None:
    actor, tender_id = _matched_org("ma6@example.com")
    s = _first(_get(actor, tender_id, limit=500), "ambiguous")
    assert _decide(actor, s["id"], "confirm").json()["status"] == "confirmed"


def test_confirm_clear_confirms_only_clear_rows_and_is_idempotent() -> None:
    actor, tender_id = _matched_org("ma7@example.com")
    lines = _get(actor, tender_id, limit=500)
    clear_ids = {s["id"] for s in _flat(lines) if s["classification"] == "clear"}
    assert clear_ids
    url = f"{API}/tenders/{tender_id}/match-suggestions/confirm-clear"
    r = actor.client.post(url)
    assert r.status_code == 200, r.text
    result = r.json()
    after = _flat(_get(actor, tender_id, limit=500))
    confirmed = {s["id"] for s in after if s["status"] == "confirmed"}
    assert result["confirmed"] == len(confirmed) and confirmed <= clear_ids
    assert result["confirmed"] + result["skipped"] == len(clear_ids)
    assert not any(s["status"] != "suggested" for s in after if s["classification"] != "clear")
    slots = [(s["boq_item_id"], s["supplier"]["id"]) for s in after if s["status"] == "confirmed"]
    assert len(slots) == len(set(slots))
    assert actor.client.post(url).json()["confirmed"] == 0
    with session_scope() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "match_confirm_clear")
        ).all()
        assert [e.event_metadata for e in event][0] == result
        assert len(event) == 2


def test_confirm_clear_skips_a_slot_that_is_already_taken_or_collides() -> None:
    actor, tender_id = _matched_org("ma8@example.com")
    first, second = _two_candidates(actor, tender_id)
    with session_scope() as db:  # make both candidates clear so they collide with each other
        db.query(MatchSuggestion).filter(
            MatchSuggestion.id.in_([UUID(first), UUID(second)])
        ).update({"classification": "clear"})
    clear_rows = [
        s for s in _flat(_get(actor, tender_id, limit=500)) if s["classification"] == "clear"
    ]
    r = actor.client.post(f"{API}/tenders/{tender_id}/match-suggestions/confirm-clear")
    assert r.status_code == 200
    assert r.json()["skipped"] >= 1
    statuses = {s["id"]: s["status"] for s in _flat(_get(actor, tender_id, limit=500))}
    assert sorted([statuses[first], statuses[second]]) == ["confirmed", "suggested"]
    assert r.json()["confirmed"] + r.json()["skipped"] == len(clear_rows)


def _replace_quotation(actor: Actor, tender_id: str, name: str, old_version: str) -> str:
    docs = actor.client.get(f"{API}/tenders/{tender_id}/documents").json()
    doc = next(d for d in docs if d["current_version"]["id"] == old_version)
    r = actor.client.post(
        f"{API}/documents/{doc['id']}/versions",
        files={"file": (name, (PACK02 / name).read_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 201, r.text
    drain()
    return r.json()["version"]["id"]


def test_a_superseded_quotation_version_is_hidden_and_its_suggestion_is_stale() -> None:
    actor, tender_id = _matched_org("ma9@example.com")
    lines = _get(actor, tender_id, limit=500)
    victim = _flat(lines)[0]
    quotation_id = victim["quotation_item"]["quotation_id"]
    assert _decide(actor, victim["id"], "reject").status_code == 200  # decided: survives re-match
    name = QUOTES[0] if "park" in victim["supplier"]["name"] else QUOTES[1]
    with session_scope() as db:
        old_version = str(db.get(Quotation, UUID(quotation_id)).document_version_id)
    new_version = _replace_quotation(actor, tender_id, name, old_version)
    after = _flat(_get(actor, tender_id, limit=500))
    assert victim["id"] not in {s["id"] for s in after}
    with session_scope() as db:
        current = {
            q.id
            for q in db.scalars(
                select(Quotation).where(Quotation.document_version_id == UUID(new_version))
            )
        }
    assert {
        UUID(s["quotation_item"]["quotation_id"])
        for s in after
        if s["supplier"]["id"] == victim["supplier"]["id"]
    } <= current
    r = _decide(actor, victim["id"], "reset")
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_match", r.text


def test_rejecting_a_boq_line_removes_it_and_queues_matching() -> None:
    actor, tender_id = _matched_org("ma10@example.com")
    lines = _get(actor, tender_id, limit=500)
    line = next(x for x in lines if x["suggestions"])
    r = actor.client.post(f"{API}/boq-items/{line['boq']['id']}/reject")
    assert r.status_code == 200, r.text
    with session_scope() as db:
        queued = db.scalars(
            select(Job).where(Job.job_type == "match_suppliers", Job.status == "queued")
        ).all()
        assert len(queued) == 1
    drain()
    after = _get(actor, tender_id, limit=500)
    assert len(after) == BOQ_LINES - 1
    assert line["boq"]["id"] not in {x["boq"]["id"] for x in after}
    assert line["boq"]["id"] not in {s["boq_item_id"] for s in _flat(after)}


def test_editing_a_boq_line_queues_matching() -> None:
    actor, tender_id = _matched_org("ma11@example.com")
    line = _get(actor, tender_id, limit=500)[0]
    r = actor.client.patch(f"{API}/boq-items/{line['boq']['id']}", json={"unit": "m"})
    assert r.status_code == 200, r.text
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Job).where(
            Job.job_type == "match_suppliers", Job.status == "queued")) == 1  # fmt: skip
    actor.client.post(
        f"{API}/boq-items/{line['boq']['id']}/confirm"
    )  # confirming queues nothing new
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Job).where(
            Job.job_type == "match_suppliers", Job.status == "queued")) == 1  # fmt: skip


def test_post_match_queues_one_job_that_succeeds() -> None:
    actor, tender_id = _matched_org("ma12@example.com")
    first = actor.client.post(f"{API}/tenders/{tender_id}/match")
    assert first.status_code == 202, first.text
    job = first.json()
    assert job["job_type"] == "match_suppliers" and job["status"] == "queued"
    assert actor.client.post(f"{API}/tenders/{tender_id}/match").json()["id"] == job["id"]
    drain()
    assert actor.client.get(f"{API}/jobs/{job['id']}").json()["status"] == "succeeded"
    other = add_member(actor, "ma12o@example.com", "estimator")
    assert other.client.post(f"{API}/tenders/{uuid4()}/match").status_code == 404


def test_roles() -> None:
    actor, tender_id = _matched_org("ma13@example.com")
    s = _flat(_get(actor, tender_id, limit=500))[0]
    for role in ("reviewer", "project_manager"):
        other = add_member(actor, f"{role}@example.com", role)
        assert len(_get(other, tender_id, limit=500)) == BOQ_LINES
        for action in ("confirm", "reject", "reset"):
            assert _decide(other, s["id"], action).status_code == 403
        assert (
            other.client.post(
                f"{API}/tenders/{tender_id}/match-suggestions/confirm-clear"
            ).status_code
            == 403
        )
        assert other.client.post(f"{API}/tenders/{tender_id}/match").status_code == 403
    estimator = add_member(actor, "est13@example.com", "estimator")
    assert _decide(estimator, s["id"], "confirm").json()["decided_by_name"] == "Member"
    assert (
        _get(actor, tender_id, status="confirmed")[0]["suggestions"][0]["decided_by_name"]
        == "Member"
    )


def test_an_archived_tender_is_read_only() -> None:
    actor, tender_id = _matched_org("ma14@example.com")
    s = _flat(_get(actor, tender_id, limit=500))[0]
    assert actor.client.post(f"{API}/tenders/{tender_id}/archive").status_code in (200, 204)
    for action in ("confirm", "reject", "reset"):
        r = _decide(actor, s["id"], action)
        assert r.status_code == 409 and r.json()["error"]["code"] == "tender_archived", action
    for path in ("match-suggestions/confirm-clear", "match"):
        r = actor.client.post(f"{API}/tenders/{tender_id}/{path}")
        assert r.status_code == 409 and r.json()["error"]["code"] == "tender_archived", path
    assert len(_get(actor, tender_id, limit=500)) == BOQ_LINES
    assert {x["status"] for x in _flat(_get(actor, tender_id, limit=500))} == {"suggested"}


def test_the_foreign_organisation_gets_404() -> None:
    from tests.conftest import register

    actor, tender_id = _matched_org("ma15@example.com")
    s = _flat(_get(actor, tender_id, limit=500))[0]
    other = register("ma15b@example.com", org="Other")
    assert other.client.get(f"{API}/tenders/{tender_id}/match-suggestions").status_code == 404
    assert _decide(other, s["id"], "confirm").status_code == 404
    assert other.client.post(f"{API}/tenders/{tender_id}/match").status_code == 404
