"""Estimates API: pricing defaults."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from app.db.session import session_scope
from app.kernel import OrgContext, Role
from app.modules.audit.models import AuditEvent
from app.modules.estimates import public as estimates
from app.modules.estimates.models import EstimateLine
from tests.conftest import add_member, make_tender, register
from tests.test_suppliers_api import _matched_org

API = "/api/v1"
URL = f"{API}/pricing-defaults"
TENDERS = f"{API}/tenders"
GOOD = {
    "currency": "ZAR",
    "vat_rate": "15",
    "markup_basis": "cost",
    "default_markup_percent": "12.5",
}


def test_put_then_get_round_trips_and_audits() -> None:
    admin = register("pd1@example.com")
    r = admin.client.put(URL, json=GOOD)
    assert r.status_code == 200, r.text
    got = admin.client.get(URL)
    assert got.status_code == 200
    body = got.json()
    assert body["currency"] == "ZAR" and body["markup_basis"] == "cost"
    assert body["vat_rate"] == "15.00" and body["default_markup_percent"] == "12.50"
    assert body["updated_at"]
    again = admin.client.put(URL, json={**GOOD, "default_markup_percent": "20"})
    assert again.status_code == 200
    assert admin.client.get(URL).json()["default_markup_percent"] == "20.00"
    with session_scope() as s:
        events = s.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "pricing_defaults_changed",
                AuditEvent.organisation_id == UUID(admin.org_id),
            )
        ).all()
    assert len(events) == 2
    assert "ZAR" not in str([e.event_metadata for e in events])


def test_roles() -> None:
    admin = register("pd2@example.com")
    estimator = add_member(admin, "pd2e@example.com", "estimator")
    reviewer = add_member(admin, "pd2r@example.com", "reviewer")
    assert estimator.client.put(URL, json=GOOD).status_code == 403
    assert reviewer.client.put(URL, json=GOOD).status_code == 403
    assert admin.client.put(URL, json=GOOD).status_code == 200
    assert reviewer.client.get(URL).status_code == 200
    assert estimator.client.get(URL).status_code == 200


def test_missing_defaults_is_404_with_code() -> None:
    admin = register("pd3@example.com")
    r = admin.client.get(URL)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "pricing_defaults_missing"


def test_invalid_values_are_422() -> None:
    admin = register("pd4@example.com")
    for patch in (
        {"vat_rate": "101"},
        {"vat_rate": "15.005"},
        {"markup_basis": "selling_price", "default_markup_percent": "99.995"},
        {"default_markup_percent": "-1"},
        {"markup_basis": "selling_price", "default_markup_percent": "100"},
        {"default_markup_percent": "1000.01"},
        {"currency": "zar"},
        {"currency": "ZARR"},
        {"markup_basis": "other"},
        {"vat_rate": "abc"},
        {"extra": "x"},
    ):
        r = admin.client.put(URL, json={**GOOD, **patch})
        assert r.status_code == 422, (patch, r.text)
    assert admin.client.get(URL).status_code == 404


def test_defaults_are_per_organisation() -> None:
    a = register("pd5a@example.com")
    b = register("pd5b@example.com")
    assert a.client.put(URL, json=GOOD).status_code == 200
    assert b.client.get(URL).status_code == 404


# --- create and read lines -------------------------------------------------------------------


def _confirm(actor, tender_id: str, count: int = 2) -> list[dict]:
    """Confirm the first suggestion of `count` different BoQ lines; returns the confirmed rows."""
    lines = actor.client.get(f"{TENDERS}/{tender_id}/match-suggestions", params={"limit": 500})
    done: list[dict] = []
    for line in lines.json():
        if line["suggestions"] and len(done) < count:
            s = line["suggestions"][0]
            r = actor.client.post(f"{API}/match-suggestions/{s['id']}/confirm")
            assert r.status_code == 200, r.text
            done.append(s)
    return done


def _estimates_ready(email: str):
    actor, tender_id = _matched_org(email)
    assert actor.client.put(URL, json=GOOD).status_code == 200
    return actor, tender_id


def test_create_lists_every_boq_line_unresolved_in_boq_order() -> None:
    actor, tender_id = _estimates_ready("ec1@example.com")
    boq = actor.client.get(f"{TENDERS}/{tender_id}/match-suggestions", params={"limit": 500}).json()
    r = actor.client.post(f"{TENDERS}/{tender_id}/estimates")
    assert r.status_code == 201, r.text
    est = r.json()
    assert est["version"] == 1 and est["status"] == "draft" and est["currency"] == "ZAR"
    assert est["vat_rate"] == "15.00" and est["markup_percent"] == "12.50"
    assert (est["priced"], est["excluded"], est["unresolved"], est["changed"]) == (0, 0, 20, 0)
    assert est["incomplete"] is True
    assert est["totals"]["total_inc_vat"] == "0.00"
    lines = actor.client.get(f"{API}/estimates/{est['id']}/lines", params={"limit": 100})
    assert lines.status_code == 200, lines.text
    body = lines.json()
    assert [x["boq_item_id"] for x in body] == [x["boq"]["id"] for x in boq]
    assert {x["price_source"] for x in body} == {"unresolved"}
    assert {x["status"] for x in body} == {"unresolved"}
    assert all(x["match_suggestion_id"] is None and x["total"] is None for x in body)
    assert all(x["candidates"] == [] for x in body)  # nothing is confirmed yet
    assert actor.client.get(f"{TENDERS}/{tender_id}/estimates").json()[0]["id"] == est["id"]
    assert actor.client.get(f"{API}/estimates/{est['id']}").json()["id"] == est["id"]


def test_create_refusals() -> None:
    actor, tender_id = _matched_org("ec2@example.com")
    first = actor.client.post(f"{TENDERS}/{tender_id}/estimates")
    assert first.status_code == 409 and first.json()["error"]["code"] == "pricing_defaults_missing"
    assert actor.client.put(URL, json=GOOD).status_code == 200
    reviewer = add_member(actor, "ec2r@example.com", "reviewer")
    assert reviewer.client.post(f"{TENDERS}/{tender_id}/estimates").status_code == 403
    assert actor.client.post(f"{TENDERS}/{tender_id}/estimates").status_code == 201
    again = actor.client.post(f"{TENDERS}/{tender_id}/estimates")
    assert again.status_code == 409 and again.json()["error"]["code"] == "draft_exists"
    other = make_tender(actor, "Second")
    assert actor.client.post(f"{TENDERS}/{other}/estimates").status_code == 201
    third = make_tender(actor, "Archived")
    assert actor.client.post(f"{TENDERS}/{third}/archive").status_code == 200
    r = actor.client.post(f"{TENDERS}/{third}/estimates")
    assert r.status_code == 409 and r.json()["error"]["code"] == "tender_archived"
    assert actor.client.post(f"{TENDERS}/{uuid4()}/estimates").status_code == 404


def test_lines_show_confirmed_candidates_only_in_supplier_order() -> None:
    actor, tender_id = _estimates_ready("ec3@example.com")
    confirmed = _confirm(actor, tender_id, 3)
    est = actor.client.post(f"{TENDERS}/{tender_id}/estimates").json()
    base = f"{API}/estimates/{est['id']}/lines"
    body = actor.client.get(base, params={"limit": 100}).json()
    with_candidates = [x for x in body if x["candidates"]]
    assert {x["boq_item_id"] for x in with_candidates} == {s["boq_item_id"] for s in confirmed}
    assert {c["match_id"] for x in with_candidates for c in x["candidates"]} == {
        s["id"] for s in confirmed
    }
    for x in body:
        names = [c["supplier_name"].lower() for c in x["candidates"]]
        assert names == sorted(names)
        assert x["match_suggestion_id"] is None and x["price_source"] == "unresolved"
    one = with_candidates[0]["candidates"][0]
    assert set(one) >= {"unit_price", "currency", "includes_vat", "warnings"}
    # the status filter is computed first, then the page is cut
    assert len(actor.client.get(base, params={"status": "unresolved"}).json()) == 20
    assert actor.client.get(base, params={"status": "priced"}).json() == []
    page = actor.client.get(base, params={"status": "unresolved", "limit": 5, "offset": 5})
    assert [x["boq_item_id"] for x in page.json()] == [x["boq_item_id"] for x in body[5:10]]
    for bad in ({"status": "bogus"}, {"limit": 0}, {"limit": 1001}, {"offset": -1}):
        assert actor.client.get(base, params=bad).status_code == 422, bad


def test_candidate_warnings_for_unknown_vat_basis_and_missing_currency() -> None:
    from app.modules.suppliers.models import Quotation

    actor, tender_id = _estimates_ready("ec4@example.com")
    confirmed = _confirm(actor, tender_id, 8)
    quotes = sorted({s["quotation_item"]["quotation_id"] for s in confirmed})
    assert len(quotes) == 2, "the fixture has two quotations"
    with session_scope() as s:  # one quotation with no VAT basis, the other with no currency
        rows = {str(q.id): q for q in s.scalars(select(Quotation))}
        rows[quotes[0]].prices_include_vat = None
        rows[quotes[1]].currency = None
    est = actor.client.post(f"{TENDERS}/{tender_id}/estimates").json()
    body = actor.client.get(f"{API}/estimates/{est['id']}/lines", params={"limit": 100}).json()
    by_match = {c["match_id"]: c for x in body for c in x["candidates"]}
    for s in confirmed:
        c = by_match[s["id"]]
        if s["quotation_item"]["quotation_id"] == quotes[0]:
            assert "vat_basis_unknown" in c["warnings"] and c["includes_vat"] is None
        else:
            assert "currency_missing" in c["warnings"] and c["currency"] is None


def test_another_organisation_gets_404() -> None:
    a, tender_id = _estimates_ready("ec5a@example.com")
    est = a.client.post(f"{TENDERS}/{tender_id}/estimates").json()
    b = register("ec5b@example.com")
    assert b.client.get(f"{API}/estimates/{est['id']}").status_code == 404
    assert b.client.get(f"{API}/estimates/{est['id']}/lines").status_code == 404
    assert b.client.get(f"{TENDERS}/{tender_id}/estimates").status_code == 404
    assert b.client.post(f"{TENDERS}/{tender_id}/estimates").status_code == 404


# --- live change detection (service level, fabricated live inputs) ---------------------------


def _live_setup(email: str, quantities=("10", "5", "7")):
    actor = register(email)
    ctx = OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)
    tender_id = UUID(make_tender(actor))
    boq = [
        estimates.BoqInput(uuid4(), "S", str(n), f"Item {n}", "m", Decimal(q), "confirmed")
        for n, q in enumerate(quantities, start=1)
    ]
    with session_scope() as s:
        estimates.save_defaults(s, ctx, estimates.PricingDefaultsPut(**GOOD))
        dto = estimates.create_estimate(s, ctx, tender_id, boq)
    return ctx, dto, boq


def _cand(boq_id, **over):
    values = {
        "match_id": uuid4(), "boq_item_id": boq_id, "quotation_item_id": uuid4(),
        "supplier_id": uuid4(), "supplier_name": "Sparkmore", "unit_price": Decimal("5.0000"),
        "currency": "ZAR", "includes_vat": False, "unit_mismatch": False,
        "quote_item_reviewed": True,
    }  # fmt: skip
    return estimates.CandidateInput(**{**values, **over})


def _cand_like(c, **over):
    return replace(c, **over)


def _choose(estimate_id, boq, cand, with_amounts=True):
    """What Task 6 will do through the API: snapshot a chosen price on a line."""
    with session_scope() as s:
        line = s.scalars(
            select(EstimateLine).where(
                EstimateLine.estimate_id == estimate_id, EstimateLine.boq_item_id == boq.id
            )
        ).one()
        line.price_source = "supplier"
        line.match_suggestion_id = cand.match_id
        line.input_hash = estimates.input_hash(boq, cand)
        line.unit_price_ex_vat = Decimal("5.0000")
        if with_amounts:
            line.material_cost = line.cost = line.total = Decimal("50.00")
            line.labour_cost = line.markup = Decimal("0.00")


def _statuses(ctx, estimate_id, live, status=None):
    with session_scope() as s:
        lines = estimates.list_lines(s, ctx, estimate_id, live, status, 100, 0)
        dto = estimates.get_estimate(s, ctx, estimate_id, live)
    return lines, dto


def test_source_changed_is_computed_against_live_inputs() -> None:
    ctx, est, boq = _live_setup("lc1@example.com")
    cands = [_cand(boq[0].id), _cand(boq[1].id)]
    _choose(est.id, boq[0], cands[0])
    _choose(est.id, boq[1], cands[1])
    base_boq = {b.id: b for b in boq}
    base_c = {c.boq_item_id: [c] for c in cands}
    lines, dto = _statuses(ctx, est.id, estimates.LiveInputs(base_boq, base_c))
    assert [x.status for x in lines] == ["priced", "priced", "unresolved"]
    assert "source_changed" not in lines[0].flags
    assert (dto.priced, dto.unresolved, dto.changed) == (2, 1, 0)

    def changed(live_boq, live_cands):
        lines, dto = _statuses(ctx, est.id, estimates.LiveInputs(live_boq, live_cands))
        return [x for x in lines if "source_changed" in x.flags], dto

    edited = {**base_boq, boq[0].id: replace(boq[0], quantity=Decimal("11"))}
    got, dto = changed(edited, base_c)
    assert [x.boq_item_id for x in got] == [boq[0].id] and got[0].status == "changed"
    assert dto.changed == 1 and dto.priced == 1 and dto.incomplete
    repriced = {**base_c, boq[1].id: [_cand_like(cands[1], unit_price=Decimal("6.0000"))]}
    assert [x.boq_item_id for x in changed(base_boq, repriced)[0]] == [boq[1].id]
    flipped = {**base_c, boq[1].id: [_cand_like(cands[1], includes_vat=True)]}
    assert [x.boq_item_id for x in changed(base_boq, flipped)[0]] == [boq[1].id]
    reset = {**base_c, boq[0].id: []}  # the chosen match is no longer confirmed and current
    assert [x.boq_item_id for x in changed(base_boq, reset)[0]] == [boq[0].id]
    other_match = {**base_c, boq[0].id: [_cand(boq[0].id)]}
    assert [x.boq_item_id for x in changed(base_boq, other_match)[0]] == [boq[0].id]
    gone = {k: v for k, v in base_boq.items() if k != boq[1].id}  # the BoQ line is gone
    got, dto = changed(gone, base_c)
    assert [x.boq_item_id for x in got] == [boq[1].id] and dto.changed == 1
    lines, _ = _statuses(ctx, est.id, estimates.LiveInputs())  # nothing live: nothing errors
    assert {x.boq_item_id for x in lines if x.status == "changed"} == {boq[0].id, boq[1].id}
    only, _ = _statuses(ctx, est.id, estimates.LiveInputs(), "changed")
    assert len(only) == 2


def test_unreviewed_sources_count_as_unresolved() -> None:
    ctx, est, boq = _live_setup("lc2@example.com", ("10", "5"))
    c = _cand(boq[0].id)
    _choose(est.id, boq[0], c)
    live = estimates.LiveInputs({b.id: b for b in boq}, {boq[0].id: [c]})
    lines, dto = _statuses(ctx, est.id, live)
    assert lines[0].status == "priced" and (dto.priced, dto.unresolved) == (1, 1)
    unreviewed_boq = {**live.boq, boq[0].id: replace(boq[0], review_status="unreviewed")}
    lines, dto = _statuses(ctx, est.id, estimates.LiveInputs(unreviewed_boq, live.candidates))
    assert lines[0].status == "unresolved" and "unreviewed_source" in lines[0].flags
    assert (dto.priced, dto.unresolved, dto.changed) == (0, 2, 0)
    unreviewed_quote = estimates.LiveInputs(
        live.boq, {boq[0].id: [_cand_like(c, quote_item_reviewed=False)]}
    )
    lines, _ = _statuses(ctx, est.id, unreviewed_quote)
    assert lines[0].status == "unresolved" and "unreviewed_source" in lines[0].flags


def test_blocked_candidates_show_warnings_and_stored_blockers_keep_a_line_unpriced() -> None:
    ctx, est, boq = _live_setup("lc3@example.com", ("10", "5"))
    no_vat = _cand(boq[0].id, includes_vat=None)
    no_cur = _cand(boq[1].id, currency=None, unit_mismatch=True)
    live = estimates.LiveInputs({b.id: b for b in boq}, {boq[0].id: [no_vat], boq[1].id: [no_cur]})
    lines, _ = _statuses(ctx, est.id, live)
    assert lines[0].candidates[0].warnings == ["vat_basis_unknown"]
    assert lines[1].candidates[0].warnings == ["currency_missing", "unit_mismatch"]
    assert lines[0].match_suggestion_id is None and lines[0].status == "unresolved"
    _choose(est.id, boq[0], no_vat)
    with session_scope() as s:
        row = s.scalars(select(EstimateLine).where(EstimateLine.boq_item_id == boq[0].id)).one()
        row.flags = {"vat_basis_unknown": True}
    lines, _ = _statuses(ctx, est.id, live)
    assert lines[0].status == "unresolved" and "vat_basis_unknown" in lines[0].flags
    assert _statuses(ctx, est.id, live, "priced")[0] == []


def test_a_merged_supplier_makes_the_line_changed() -> None:
    ctx, est, boq = _live_setup("lc4@example.com", ("10",))
    c = _cand(boq[0].id)
    _choose(est.id, boq[0], c)
    base = {b.id: b for b in boq}
    assert _statuses(ctx, est.id, estimates.LiveInputs(base, {boq[0].id: [c]}))[0][0].status == (
        "priced"
    )
    merged = _cand_like(c, supplier_id=uuid4(), supplier_name="Greenvale")  # same match id
    lines, dto = _statuses(ctx, est.id, estimates.LiveInputs(base, {boq[0].id: [merged]}))
    assert lines[0].status == "changed" and "source_changed" in lines[0].flags
    assert dto.changed == 1 and dto.incomplete


def test_a_supplier_line_without_amounts_is_unresolved_and_incomplete() -> None:
    ctx, est, boq = _live_setup("lc5@example.com", ("10",))
    c = _cand(boq[0].id)
    _choose(est.id, boq[0], c, with_amounts=False)
    live = estimates.LiveInputs({b.id: b for b in boq}, {boq[0].id: [c]})
    lines, dto = _statuses(ctx, est.id, live)
    assert lines[0].status == "unresolved" and lines[0].total is None
    assert (dto.priced, dto.unresolved) == (0, 1) and dto.incomplete
    assert dto.totals.total_inc_vat == "0.00"
