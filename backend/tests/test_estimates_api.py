"""Estimates API: pricing defaults."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
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


# --- price a line, refresh, settings ---------------------------------------------------------

LINES = f"{API}/estimate-lines"


def _quotes(include_vat=False, currency="ZAR") -> None:
    from app.modules.estimating.models import BoqItem
    from app.modules.suppliers.models import Quotation, QuotationItem

    with session_scope() as s:
        for q in s.scalars(select(Quotation)):
            q.prices_include_vat = include_vat
            q.currency = currency
        for row in (*s.scalars(select(BoqItem)), *s.scalars(select(QuotationItem))):
            row.review_status = "confirmed"  # unreviewed sources block pricing (BR-01)


def _priced_setup(email: str, include_vat=False, currency="ZAR", count=4):
    actor, tender_id = _estimates_ready(email)
    _confirm(actor, tender_id, count)
    _quotes(include_vat, currency)
    est = actor.client.post(f"{TENDERS}/{tender_id}/estimates").json()
    return actor, tender_id, est


def _lines(actor, est) -> list[dict]:
    return actor.client.get(f"{API}/estimates/{est['id']}/lines", params={"limit": 100}).json()


def _line(actor, est, line_id) -> dict:
    return next(x for x in _lines(actor, est) if x["id"] == line_id)


def _usable(actor, est) -> list[dict]:
    """Lines with a confirmed candidate that has a price, a quantity and no unit mismatch."""
    return [
        x
        for x in _lines(actor, est)
        if x["candidates"]
        and x["candidates"][0]["unit_price"]
        and "unit_mismatch" not in x["candidates"][0]["warnings"]
        and x["quantity"] is not None
        and Decimal(x["quantity"]) > 0
    ]


def _put(actor, line, **body):
    return actor.client.put(f"{LINES}/{line['id']}", json=body)


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")


def _ex(price: str, rate: str) -> Decimal:
    return (Decimal(price) / (1 + Decimal(rate) / 100)).quantize(
        Decimal("0.0001"), rounding="ROUND_HALF_UP"
    )


def test_choosing_a_confirmed_match_prices_the_line_with_golden_maths() -> None:
    actor, _, est = _priced_setup("pl1@example.com")
    line = _usable(actor, est)[0]
    cand = line["candidates"][0]
    r = _put(actor, line, match_suggestion_id=cand["match_id"], labour_rate="2")
    assert r.status_code == 200, r.text
    got = r.json()
    qty, price = Decimal(line["quantity"]), Decimal(cand["unit_price"])
    material, labour = _round2(qty * price), _round2(qty * Decimal("2"))
    markup = _round2((material + labour) * Decimal("0.125"))
    assert got["status"] == "priced" and got["price_source"] == "supplier"
    assert got["match_suggestion_id"] == cand["match_id"] and got["flags"] == []
    assert got["supplier_name"] == cand["supplier_name"]
    assert (got["material_cost"], got["labour_cost"]) == (str(material), str(labour))
    assert got["cost"] == str(material + labour) and got["markup"] == str(markup)
    assert got["total"] == str(material + labour + markup)
    assert got["unit_price_ex_vat"] == str(price.quantize(Decimal("0.0001")))
    est_after = actor.client.get(f"{API}/estimates/{est['id']}").json()
    assert est_after["priced"] == 1 and est_after["totals"]["subtotal_ex_vat"] == got["total"]
    with session_scope() as s:
        row = s.get(EstimateLine, UUID(line["id"]))
        assert row.flags == {} and row.input_hash


def test_a_vat_inclusive_quote_is_divided_by_one_plus_the_rate() -> None:
    actor, _, est = _priced_setup("pl2@example.com", include_vat=True)
    line = _usable(actor, est)[0]
    cand = line["candidates"][0]
    got = _put(actor, line, match_suggestion_id=cand["match_id"]).json()
    ex = _ex(cand["unit_price"], "15")
    assert got["unit_price_ex_vat"] == str(ex) and got["quoted_includes_vat"] is True
    assert got["quoted_unit_price"] == cand["unit_price"]
    assert got["material_cost"] == str(_round2(Decimal(line["quantity"]) * ex))


def test_manual_price_and_exclusion() -> None:
    actor, _, est = _priced_setup("pl3@example.com")
    a, b = _usable(actor, est)[:2]
    got = _put(actor, a, manual_unit_price="10.5", markup_override_percent="0").json()
    assert got["price_source"] == "manual" and got["status"] == "priced"
    assert got["unit_price_ex_vat"] == "10.5000" and got["match_suggestion_id"] is None
    expected = _round2(Decimal(a["quantity"]) * Decimal("10.5"))
    assert got["material_cost"] == str(expected) and got["markup"] == "0.00"
    assert got["total"] == str(expected)
    assert _put(actor, b, exclude_reason="").status_code == 422
    assert _put(actor, b, exclude_reason="x" * 301).status_code == 422
    ex = _put(actor, b, exclude_reason="  Client supplies  ").json()
    assert ex["status"] == "excluded" and ex["exclude_reason"] == "Client supplies"
    assert ex["total"] is None and ex["cost"] is None
    for bad in ("0", "-1", "1.00001", "abc"):
        assert _put(actor, a, manual_unit_price=bad).status_code == 422, bad
    again = _put(actor, a, exclude_reason="changed mind").json()  # a priced line can be excluded
    assert again["status"] == "excluded" and again["total"] is None
    with session_scope() as s:
        events = s.scalars(select(AuditEvent).where(AuditEvent.action.like("estimate_line_%")))
        text = str([e.event_metadata for e in events])
    assert "Client supplies" not in text and "10.5" not in text


def test_exactly_one_source_and_strict_bodies() -> None:
    actor, _, est = _priced_setup("pl4@example.com")
    line = _usable(actor, est)[0]
    cand = line["candidates"][0]["match_id"]
    for body in (
        {},
        {"labour_rate": "1"},
        {"match_suggestion_id": cand, "manual_unit_price": "5"},
        {"manual_unit_price": "5", "exclude_reason": "x"},
        {"match_suggestion_id": cand, "exclude_reason": "x"},
        {"manual_unit_price": "5", "extra": 1},
        {"manual_unit_price": "5", "labour_rate": "-1"},
        {"manual_unit_price": "5", "markup_override_percent": "-1"},
        {"manual_unit_price": "5", "markup_override_percent": "1000.01"},
    ):
        assert _put(actor, line, **body).status_code == 422, body
    # the override range follows the estimate's basis: 100 or more is refused on selling_price
    url = f"{API}/estimates/{est['id']}"
    assert actor.client.patch(url, json={"markup_basis": "selling_price"}).status_code == 200
    assert (
        _put(actor, line, manual_unit_price="5", markup_override_percent="100").status_code == 422
    )
    ok = _put(actor, line, manual_unit_price="5", markup_override_percent="99.99")
    assert ok.status_code == 200


def test_stale_and_foreign_matches_are_conflicts() -> None:
    actor, tender_id, est = _priced_setup("pl5@example.com", count=4)
    a, b = _usable(actor, est)[:2]
    other = b["candidates"][0]["match_id"]
    r = _put(actor, a, match_suggestion_id=other)  # another BoQ line's match
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_match"
    unconfirmed = next(
        s
        for x in actor.client.get(
            f"{TENDERS}/{tender_id}/match-suggestions", params={"limit": 500}
        ).json()
        for s in x["suggestions"]
        if s["status"] != "confirmed"
    )
    r = _put(actor, a, match_suggestion_id=unconfirmed["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_match"
    r = _put(actor, a, match_suggestion_id=str(uuid4()))
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_match"
    # reset the chosen match after pricing: the line shows changed, a refresh is a conflict
    mid = a["candidates"][0]["match_id"]
    assert _put(actor, a, match_suggestion_id=mid).status_code == 200
    assert actor.client.post(f"{API}/match-suggestions/{mid}/reset").status_code == 200
    after = _line(actor, est, a["id"])
    assert after["status"] == "changed" and "source_changed" in after["flags"]
    r = actor.client.post(f"{LINES}/{a['id']}/refresh")
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_match"


def test_unit_mismatch_needs_acknowledgement() -> None:
    actor, _, est = _priced_setup("pl6@example.com", count=8)
    line = next(
        (
            x
            for x in _lines(actor, est)
            if x["candidates"]
            and "unit_mismatch" in x["candidates"][0]["warnings"]
            and x["quantity"]
            and Decimal(x["quantity"]) > 0
            and x["candidates"][0]["unit_price"]
        ),
        None,
    )
    if line is None:
        pytest.skip("the fixture has no confirmed unit-mismatch candidate")
    mid = line["candidates"][0]["match_id"]
    r = _put(actor, line, match_suggestion_id=mid)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unit_mismatch_unacknowledged"
    ok = _put(actor, line, match_suggestion_id=mid, unit_mismatch_acknowledged=True)
    assert ok.status_code == 200 and ok.json()["unit_mismatch_acknowledged"] is True


def test_blockers_leave_the_line_unresolved_without_amounts() -> None:
    from app.modules.suppliers.models import Quotation

    cases = [
        (None, "ZAR", "vat_basis_unknown"),
        (False, None, "currency_missing"),
        (False, "USD", "currency_differs"),
    ]
    for n, (vat, cur, flag) in enumerate(cases):
        actor, _, est = _priced_setup(f"pl7{n}@example.com")
        with session_scope() as s:
            for q in s.scalars(select(Quotation)):
                q.prices_include_vat, q.currency = vat, cur
        line = _usable(actor, est)[0]
        got = _put(actor, line, match_suggestion_id=line["candidates"][0]["match_id"]).json()
        assert got["status"] == "unresolved" and flag in got["flags"], (flag, got)
        assert got["match_suggestion_id"] and got["supplier_name"]
        for k in ("material_cost", "labour_cost", "cost", "markup", "total"):
            assert got[k] is None
        assert actor.client.get(f"{API}/estimates/{est['id']}").json()["priced"] == 0
        with session_scope() as s:
            assert s.get(EstimateLine, UUID(line["id"])).flags == {flag: True}


def test_resolving_the_vat_basis_shows_source_changed_and_refresh_reprices() -> None:
    from app.modules.suppliers.models import Quotation, QuotationItem

    actor, _, est = _priced_setup("pl8@example.com")
    with session_scope() as s:
        for q in s.scalars(select(Quotation)):
            q.prices_include_vat = None
    line = _usable(actor, est)[0]
    cand = line["candidates"][0]
    assert _put(actor, line, match_suggestion_id=cand["match_id"]).json()["status"] == "unresolved"
    with session_scope() as s:
        quotation_id = s.get(QuotationItem, UUID(cand["quotation_item_id"])).quotation_id
    r = actor.client.patch(f"{API}/quotations/{quotation_id}", json={"prices_include_vat": True})
    assert r.status_code == 200, r.text
    now = _line(actor, est, line["id"])
    assert now["status"] == "changed" and "source_changed" in now["flags"]
    got = actor.client.post(f"{LINES}/{line['id']}/refresh").json()
    assert got["status"] == "priced" and got["unit_price_ex_vat"] == str(
        _ex(cand["unit_price"], "15")
    )
    assert "source_changed" not in got["flags"] and got["total"] is not None


def test_editing_the_boq_quantity_shows_source_changed_and_refresh_clears_it() -> None:
    from app.modules.estimating.models import BoqItem

    actor, _, est = _priced_setup("pl9@example.com")
    line = _usable(actor, est)[0]
    assert _put(actor, line, manual_unit_price="4").json()["status"] == "priced"
    with session_scope() as s:
        s.get(BoqItem, UUID(line["boq_item_id"])).quantity = Decimal("123.5")
    now = _line(actor, est, line["id"])
    assert now["status"] == "changed" and "source_changed" in now["flags"]
    assert now["quantity"] == line["quantity"]  # the snapshot is untouched until refreshed
    assert actor.client.get(f"{API}/estimates/{est['id']}").json()["changed"] == 1
    got = actor.client.post(f"{LINES}/{line['id']}/refresh").json()
    assert got["quantity"] == "123.5000" and got["status"] == "priced"
    assert got["material_cost"] == "494.00" and "source_changed" not in got["flags"]
    with session_scope() as s:
        s.get(BoqItem, UUID(line["boq_item_id"])).quantity = None
    assert _line(actor, est, line["id"])["status"] == "changed"
    got = actor.client.post(f"{LINES}/{line['id']}/refresh").json()
    assert got["status"] == "unresolved" and "quantity_missing" in got["flags"]
    assert got["total"] is None
    # a line with no quantity can only be excluded
    assert _put(actor, line, manual_unit_price="4").status_code == 422
    assert _put(actor, line, exclude_reason="rate only").json()["status"] == "excluded"


def test_patching_vat_and_markup_recomputes_every_line() -> None:
    actor, _, est = _priced_setup("pl10@example.com", include_vat=True)
    a, b = _usable(actor, est)[:2]
    _put(actor, a, match_suggestion_id=a["candidates"][0]["match_id"])
    _put(actor, b, manual_unit_price="3")
    r = actor.client.patch(f"{API}/estimates/{est['id']}", json={"vat_rate": "20"})
    assert r.status_code == 200, r.text
    assert r.json()["vat_rate"] == "20.00"
    lines = {x["id"]: x for x in _lines(actor, est)}
    ex = _ex(a["candidates"][0]["unit_price"], "20")
    assert lines[a["id"]]["unit_price_ex_vat"] == str(ex)
    assert lines[a["id"]]["material_cost"] == str(_round2(Decimal(a["quantity"]) * ex))
    assert lines[b["id"]]["unit_price_ex_vat"] == "3.0000"
    totals = r.json()["totals"]
    subtotal = sum(Decimal(x["total"]) for x in lines.values() if x["total"])
    assert totals["subtotal_ex_vat"] == str(subtotal)
    assert totals["vat_total"] == str(_round2(subtotal * Decimal("0.2")))
    r = actor.client.patch(f"{API}/estimates/{est['id']}", json={"markup_percent": "0"})
    assert r.json()["totals"]["markup_total"] == "0.00"
    lines = {x["id"]: x for x in _lines(actor, est)}
    assert all(x["markup"] == "0.00" for x in lines.values() if x["total"])
    with session_scope() as s:
        events = s.scalars(
            select(AuditEvent).where(AuditEvent.action == "estimate_settings_changed")
        ).all()
    assert sorted(str(e.event_metadata) for e in events) == sorted(
        [str({"fields": ["vat_rate"]}), str({"fields": ["markup_percent"]})]
    )


def test_patch_validation_and_currency_lock() -> None:
    actor, _, est = _priced_setup("pl11@example.com")
    url = f"{API}/estimates/{est['id']}"
    for bad in (
        {},
        {"vat_rate": None},
        {"vat_rate": "101"},
        {"markup_percent": "1000.01"},
        {"currency": "usd"},
        {"markup_basis": "x"},
        {"extra": 1},
    ):
        assert actor.client.patch(url, json=bad).status_code == 422, bad
    body = {"markup_percent": "99", "markup_basis": "selling_price"}
    assert actor.client.patch(url, json=body).status_code == 200
    assert actor.client.patch(url, json={"markup_percent": "100"}).status_code == 422
    assert actor.client.patch(url, json={"currency": "USD"}).json()["currency"] == "USD"
    line = _usable(actor, est)[0]
    _put(actor, line, manual_unit_price="2")
    r = actor.client.patch(url, json={"currency": "EUR"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "currency_locked"
    assert actor.client.get(url).json()["currency"] == "USD"
    # an override that the new basis cannot hold is refused
    assert (
        actor.client.patch(url, json={"markup_basis": "cost", "markup_percent": "5"}).status_code
        == 200
    )
    assert (
        _put(actor, line, manual_unit_price="2", markup_override_percent="500").status_code == 200
    )
    assert actor.client.patch(url, json={"markup_basis": "selling_price"}).status_code == 422


def test_a_blocked_supplier_line_also_holds_the_currency() -> None:
    actor, _, est = _priced_setup("pl12@example.com", currency="EUR")
    line = _usable(actor, est)[0]
    got = _put(actor, line, match_suggestion_id=line["candidates"][0]["match_id"]).json()
    assert "currency_differs" in got["flags"]
    r = actor.client.patch(f"{API}/estimates/{est['id']}", json={"currency": "EUR"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "currency_locked"


def _excl(line_id) -> str:
    return f"{LINES}/{line_id}"


def test_write_permissions_archive_and_frozen() -> None:
    from app.modules.estimates.models import Estimate

    actor, tender_id, est = _priced_setup("pl13@example.com")
    line = _usable(actor, est)[0]
    body = {"exclude_reason": "x"}
    patch = f"{API}/estimates/{est['id']}"
    reviewer = add_member(actor, "pl13r@example.com", "reviewer")
    assert reviewer.client.put(_excl(line["id"]), json=body).status_code == 403
    assert reviewer.client.post(f"{LINES}/{line['id']}/refresh").status_code == 403
    assert reviewer.client.patch(patch, json={"vat_rate": "1"}).status_code == 403
    assert actor.client.put(_excl(uuid4()), json=body).status_code == 404
    assert (
        actor.client.patch(f"{API}/estimates/{uuid4()}", json={"vat_rate": "1"}).status_code == 404
    )
    other = register("pl13b@example.com")
    assert other.client.put(_excl(line["id"]), json=body).status_code == 404
    assert other.client.post(f"{LINES}/{line['id']}/refresh").status_code == 404
    assert other.client.patch(patch, json={"vat_rate": "1"}).status_code == 404

    def attempts():
        return (
            actor.client.put(_excl(line["id"]), json=body),
            actor.client.post(f"{LINES}/{line['id']}/refresh"),
            actor.client.patch(patch, json={"vat_rate": "1"}),
        )

    with session_scope() as s:
        s.get(Estimate, UUID(est["id"])).status = "reviewed"
    for r in attempts():
        assert r.status_code == 409 and r.json()["error"]["code"] == "estimate_frozen"
    with session_scope() as s:
        s.get(Estimate, UUID(est["id"])).status = "draft"
    assert actor.client.post(f"{TENDERS}/{tender_id}/archive").status_code == 200
    for r in attempts():
        assert r.status_code == 409 and r.json()["error"]["code"] == "tender_archived"


def test_no_computed_flag_is_ever_stored() -> None:
    actor, _, est = _priced_setup("pl14@example.com")
    for line in _usable(actor, est)[:3]:
        _put(actor, line, match_suggestion_id=line["candidates"][0]["match_id"])
    with session_scope() as s:
        for row in s.scalars(select(EstimateLine)):
            assert not {"unreviewed_source", "source_changed"} & set(row.flags or {})
            assert (row.total is None) == (row.material_cost is None) == (row.markup is None)


# --- status moves: review, reopen, approve ---------------------------------------------------


def _resolve_all(actor, est, price_first: bool = True) -> None:
    """Price the first usable line with its confirmed match, exclude every other line."""
    lines = _lines(actor, est)
    first = _usable(actor, est)[0] if price_first else None
    for line in lines:
        if first is not None and line["id"] == first["id"]:
            r = _put(actor, line, match_suggestion_id=line["candidates"][0]["match_id"])
        else:
            r = _put(actor, line, exclude_reason="Not needed")
        assert r.status_code == 200, r.text


def _move(actor, est, action: str):
    return actor.client.post(f"{API}/estimates/{est['id']}/{action}")


def _ready(email: str):
    actor, tender_id, est = _priced_setup(email)
    _resolve_all(actor, est)
    return actor, tender_id, est


def test_review_and_approve_freeze_totals_actor_and_time() -> None:
    actor, _, est = _ready("st1@example.com")
    live_totals = actor.client.get(f"{API}/estimates/{est['id']}").json()["totals"]
    assert Decimal(live_totals["total_inc_vat"]) > 0
    r = _move(actor, est, "review")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "reviewed" and body["totals"] == live_totals
    assert body["reviewed_by"] == actor.me["user_id"] and body["reviewed_at"]
    assert body["approved_by"] is None and body["incomplete"] is False
    a = _move(actor, est, "approve")
    assert a.status_code == 200, a.text
    done = a.json()
    assert done["status"] == "approved" and done["totals"] == live_totals
    assert done["approved_by"] == actor.me["user_id"] and done["approved_at"]
    assert done["reviewed_by"] == actor.me["user_id"]
    # every write is refused once frozen
    line = _lines(actor, est)[0]
    for r2 in (
        _put(actor, line, exclude_reason="x"),
        actor.client.post(f"{LINES}/{line['id']}/refresh"),
        actor.client.patch(f"{API}/estimates/{est['id']}", json={"vat_rate": "1"}),
        _move(actor, est, "review"),
        _move(actor, est, "approve"),
        _move(actor, est, "reopen"),
    ):
        assert r2.status_code == 409 and r2.json()["error"]["code"] == "estimate_frozen", r2.text
    # editing the BoQ later does not move the frozen totals
    from app.modules.estimating.models import BoqItem

    with session_scope() as s:
        for item in s.scalars(select(BoqItem)):
            item.quantity = Decimal("999")
    again = actor.client.get(f"{API}/estimates/{est['id']}").json()
    assert again["totals"] == live_totals and again["status"] == "approved"


def test_roles_for_review_approve_and_reopen() -> None:
    actor, _, est = _ready("st2@example.com")
    estimator = add_member(actor, "st2e@example.com", "estimator")
    manager = add_member(actor, "st2m@example.com", "project_manager")
    reviewer = add_member(actor, "st2r@example.com", "reviewer")
    for who in (reviewer, manager):
        assert _move(who, est, "review").status_code == 403
    assert _move(estimator, est, "review").status_code == 200
    assert _move(estimator, est, "approve").status_code == 403
    assert _move(reviewer, est, "approve").status_code == 403
    assert _move(manager, est, "reopen").status_code == 403
    assert _move(manager, est, "approve").status_code == 200
    other = register("st2o@example.com")
    for action in ("review", "reopen", "approve"):
        assert _move(other, est, action).status_code == 404
        assert _move(actor, {"id": str(uuid4())}, action).status_code == 404


def test_not_ready_lists_blockers_by_code() -> None:
    actor, tender_id, est = _priced_setup("st3@example.com")
    r = _move(actor, est, "review")
    err = r.json()["error"]
    assert r.status_code == 409 and err["code"] == "estimate_not_ready"
    blockers = err["details"]["blockers"]
    assert len(blockers) == 20 and {b["code"] for b in blockers} == {"unresolved"}
    assert {b["line_id"] for b in blockers} == {x["id"] for x in _lines(actor, est)}
    assert _move(actor, est, "approve").status_code == 409  # a draft cannot be approved
    # a changed line
    _resolve_all(actor, est)
    priced = next(x for x in _lines(actor, est) if x["status"] == "priced")
    from app.modules.estimating.models import BoqItem

    with session_scope() as s:
        s.get(BoqItem, UUID(priced["boq_item_id"])).quantity = Decimal("123")
    err = _move(actor, est, "review").json()["error"]
    assert err["code"] == "estimate_not_ready"
    assert err["details"]["blockers"] == [{"line_id": priced["id"], "code": "source_changed"}]
    # an unreviewed source
    with session_scope() as s:
        item = s.get(BoqItem, UUID(priced["boq_item_id"]))
        item.quantity = Decimal(priced["quantity"])
        item.review_status = "unreviewed"
    err = _move(actor, est, "review").json()["error"]
    assert err["details"]["blockers"] == [{"line_id": priced["id"], "code": "unreviewed_source"}]
    with session_scope() as s:
        s.get(BoqItem, UUID(priced["boq_item_id"])).review_status = "confirmed"
    assert _move(actor, est, "review").status_code == 200


def test_approving_a_draft_is_refused_and_no_lines_blocks() -> None:
    actor, _ = _estimates_ready("st4@example.com")
    empty = make_tender(actor, "Empty")
    est = actor.client.post(f"{TENDERS}/{empty}/estimates").json()
    err = _move(actor, est, "review").json()["error"]
    assert err["code"] == "estimate_not_ready"
    assert err["details"]["blockers"] == [{"line_id": None, "code": "no_lines"}]
    full, _, est2 = _ready("st4b@example.com")
    r = _move(full, est2, "approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "estimate_not_reviewed"


def test_all_excluded_estimate_approves_with_zero_totals() -> None:
    actor, _, est = _priced_setup("st5@example.com")
    _resolve_all(actor, est, price_first=False)
    assert _move(actor, est, "review").status_code == 200
    done = _move(actor, est, "approve").json()
    assert done["status"] == "approved" and done["excluded"] == 20
    assert done["totals"] == {
        "subtotal_cost": "0.00", "markup_total": "0.00", "subtotal_ex_vat": "0.00",
        "vat_total": "0.00", "total_inc_vat": "0.00",
    }  # fmt: skip


def test_reopen_returns_to_draft_and_refuses_when_another_draft_exists() -> None:
    actor, tender_id, est = _ready("st6@example.com")
    assert _move(actor, est, "reopen").status_code == 409  # a draft cannot be reopened
    assert _move(actor, est, "review").status_code == 200
    r = _move(actor, est, "reopen")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "draft" and body["reviewed_by"] is None and body["reviewed_at"] is None
    assert _move(actor, est, "review").status_code == 200
    second = actor.client.post(f"{TENDERS}/{tender_id}/estimates")
    assert second.status_code == 201, second.text  # no draft now, so a new version is allowed
    blocked = _move(actor, est, "reopen")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "draft_exists"
    assert actor.client.get(f"{API}/estimates/{est['id']}").json()["status"] == "reviewed"


def test_current_approved_version_flag_and_audit_rows() -> None:
    actor, tender_id, est = _ready("st7@example.com")
    assert _move(actor, est, "review").status_code == 200
    assert _move(actor, est, "approve").status_code == 200
    v2 = actor.client.post(f"{TENDERS}/{tender_id}/estimates").json()
    _resolve_all(actor, v2)
    assert _move(actor, v2, "review").status_code == 200
    assert _move(actor, v2, "reopen").status_code == 200
    assert _move(actor, v2, "review").status_code == 200
    assert _move(actor, v2, "approve").status_code == 200
    v3 = actor.client.post(f"{TENDERS}/{tender_id}/estimates").json()
    rows = actor.client.get(f"{TENDERS}/{tender_id}/estimates").json()
    assert [(r["version"], r["status"], r["is_current_approved"]) for r in rows] == [
        (3, "draft", False), (2, "approved", True), (1, "approved", False),
    ]  # fmt: skip
    assert v3["version"] == 3
    with session_scope() as s:
        events = s.scalars(
            select(AuditEvent).where(
                AuditEvent.organisation_id == UUID(actor.org_id),
                AuditEvent.action.in_(
                    ["estimate_reviewed", "estimate_reopened", "estimate_approved"]
                ),
            )
        ).all()
        by_action: dict[str, list] = {}
        for e in events:
            by_action.setdefault(e.action, []).append(e.event_metadata)
    assert len(by_action["estimate_reviewed"]) == 3 and len(by_action["estimate_reopened"]) == 1
    approved = by_action["estimate_approved"]
    assert len(approved) == 2
    for meta in approved:
        assert meta["reviewed_by"] == actor.me["user_id"]
        assert meta["approved_by"] == actor.me["user_id"] and meta["status"] == "approved"
        assert not {"total_inc_vat", "totals"} & set(meta)
