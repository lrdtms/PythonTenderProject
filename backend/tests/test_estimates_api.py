"""Estimates API: pricing defaults."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.session import session_scope
from app.modules.audit.models import AuditEvent
from tests.conftest import add_member, register

API = "/api/v1"
URL = f"{API}/pricing-defaults"
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
    assert float(body["vat_rate"]) == 15 and float(body["default_markup_percent"]) == 12.5
    assert body["updated_at"]
    again = admin.client.put(URL, json={**GOOD, "default_markup_percent": "20"})
    assert again.status_code == 200
    assert float(admin.client.get(URL).json()["default_markup_percent"]) == 20
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
