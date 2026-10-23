"""Estimate creation, line writes and status moves against each other.

The router takes the tender lock before the estimate row lock, so every pair below is serialised:
whichever request wins, the other must see its result."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.db.session import session_scope
from app.modules.estimates.models import Estimate, EstimateLine
from tests.conftest import add_member
from tests.test_estimates_api import (
    API,
    TENDERS,
    _estimates_ready,
    _lines,
    _move,
    _priced_setup,
    _put,
    _resolve_all,
)


def _together(*calls):
    barrier = threading.Barrier(len(calls))

    def go(call):
        barrier.wait(10)
        return call()

    with ThreadPoolExecutor(len(calls)) as pool:
        return [f.result(60) for f in [pool.submit(go, c) for c in calls]]


def test_two_concurrent_creates_give_one_draft() -> None:
    actor, tender_id = _estimates_ready("er1@example.com")
    partner = add_member(actor, "er1b@example.com", "estimator")
    results = _together(
        lambda: actor.client.post(f"{TENDERS}/{tender_id}/estimates"),
        lambda: partner.client.post(f"{TENDERS}/{tender_id}/estimates"),
    )
    assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "draft_exists"
    with session_scope() as s:
        rows = s.scalars(select(Estimate).where(Estimate.tender_id == UUID(tender_id))).all()
    assert [(e.version, e.status) for e in rows] == [(1, "draft")]


def _frozen_totals_match_lines(estimate_id: str) -> None:
    with session_scope() as s:
        est = s.get(Estimate, UUID(estimate_id))
        lines = s.scalars(
            select(EstimateLine).where(EstimateLine.estimate_id == UUID(estimate_id))
        ).all()
        assert est.status != "draft"
        assert all(r.price_source != "unresolved" for r in lines), "a frozen unresolved line"
        expected = sum((r.total for r in lines if r.total is not None), Decimal("0.00"))
        assert est.subtotal_ex_vat == expected, "frozen totals do not match the stored lines"


def test_review_racing_a_line_write_never_freezes_a_stale_total() -> None:
    actor, _, est = _priced_setup("er2@example.com")
    _resolve_all(actor, est)
    priced = next(x for x in _lines(actor, est) if x["status"] == "priced")
    review, write = _together(
        lambda: _move(actor, est, "review"),
        lambda: _put(actor, priced, manual_unit_price="77.5", markup_override_percent="0"),
    )
    assert review.status_code == 200, review.text
    assert write.status_code in (200, 409), write.text
    if write.status_code == 409:
        assert write.json()["error"]["code"] == "estimate_frozen"
    _frozen_totals_match_lines(est["id"])


def test_approve_racing_a_line_write_is_frozen_and_refuses_the_write() -> None:
    actor, _, est = _priced_setup("er3@example.com")
    _resolve_all(actor, est)
    priced = next(x for x in _lines(actor, est) if x["status"] == "priced")
    assert _move(actor, est, "review").status_code == 200
    approve, write = _together(
        lambda: _move(actor, est, "approve"),
        lambda: _put(actor, priced, manual_unit_price="77.5", markup_override_percent="0"),
    )
    assert approve.status_code == 200, approve.text
    assert write.status_code == 409 and write.json()["error"]["code"] == "estimate_frozen"
    _frozen_totals_match_lines(est["id"])
    assert actor.client.get(f"{API}/estimates/{est['id']}").json()["status"] == "approved"


def _export_race(email: str, writer_first: bool):
    from app.api import estimate_inputs
    from app.kernel import OrgContext, Role
    from app.modules.estimates import public as estimates
    from app.modules.suppliers import public as suppliers
    from tests.test_estimates_api import _ready

    actor, tender_id, est = _ready(email)
    assert _move(actor, est, "review").status_code == 200
    priced = next(x for x in _lines(actor, est) if x["status"] == "priced")
    ctx = OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)
    tender, estimate = UUID(tender_id), UUID(est["id"])
    first_has_lock, second_may_go = threading.Event(), threading.Event()

    def write(s):
        live = estimate_inputs.live_inputs(s, ctx, tender)
        estimates.reopen_estimate(s, ctx, estimate, live)
        body = estimates.LinePut(manual_unit_price="77.5", markup_override_percent="0")
        estimates.price_line(s, ctx, UUID(priced["id"]), body, live)

    def read(s):
        live = estimate_inputs.live_inputs(s, ctx, tender)
        return estimates.export_snapshot(s, ctx, estimate, live)

    def first():
        with session_scope() as s:
            suppliers.lock_tender(s, ctx, tender)
            first_has_lock.set()
            # let the second transaction reach (and block on) the lock before we finish
            assert second_may_go.wait(10)
            threading.Event().wait(0.5)
            return (write if writer_first else read)(s)

    def second():
        assert first_has_lock.wait(10)
        with session_scope() as s:
            second_may_go.set()
            suppliers.lock_tender(s, ctx, tender)
            return (read if writer_first else write)(s)

    out = _together(first, second)
    dto, lines = out[1] if writer_first else out[0]
    return priced, dto, lines


def _assert_totals_match(dto, lines) -> None:
    expected = sum((Decimal(x.total) for x in lines if x.total is not None), Decimal("0.00"))
    assert dto.totals.subtotal_ex_vat == str(expected), "totals do not match the lines"


def test_export_snapshot_after_a_reopen_and_price_sees_the_draft_entirely() -> None:
    priced, dto, lines = _export_race("er9@example.com", writer_first=True)
    assert dto.status == "draft"
    line = next(x for x in lines if str(x.id) == priced["id"])
    assert Decimal(line.unit_price_ex_vat) == Decimal("77.5")
    assert line.total != priced["total"]
    _assert_totals_match(dto, lines)


def test_export_snapshot_before_a_reopen_sees_the_reviewed_state_entirely() -> None:
    priced, dto, lines = _export_race("er10@example.com", writer_first=False)
    assert dto.status == "reviewed"
    line = next(x for x in lines if str(x.id) == priced["id"])
    assert line.unit_price_ex_vat == priced["unit_price_ex_vat"] and line.total == priced["total"]
    _assert_totals_match(dto, lines)
