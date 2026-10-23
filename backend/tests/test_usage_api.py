"""GET /usage and the mock plan switch."""

from __future__ import annotations

import pytest

from tests.conftest import Actor, add_member, make_tender, register

USAGE = "/api/v1/usage"
PLAN = f"{USAGE}/plan"


@pytest.mark.parametrize("role", ["admin", "estimator", "project_manager", "reviewer"])
def test_every_member_can_read_usage(admin: Actor, role: str) -> None:
    actor = admin if role == "admin" else add_member(admin, f"{role}@example.com", role)
    r = actor.client.get(USAGE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_code"] == "demo"
    assert {i["resource"] for i in body["items"]} == {
        "tenders",
        "uploads",
        "storage_mb",
        "exports",
        "members",
    }
    periods = {i["resource"]: i["period"] for i in body["items"]}
    assert periods == {
        "tenders": "current",
        "uploads": "month",
        "storage_mb": "current",
        "exports": "month",
        "members": "current",
    }


def test_usage_requires_a_session(client) -> None:
    assert client.get(USAGE).status_code == 401
    assert client.put(PLAN, json={"plan_code": "starter"}).status_code == 401


def test_usage_reflects_real_counts(admin: Actor) -> None:
    make_tender(admin)
    make_tender(admin)
    items = {i["resource"]: i for i in admin.client.get(USAGE).json()["items"]}
    assert items["tenders"]["used"] == 2
    assert items["members"]["used"] == 1


def test_admin_switches_plan_and_it_is_audited(admin: Actor) -> None:
    r = admin.client.put(PLAN, json={"plan_code": "starter"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_code"] == "starter"
    assert {i["resource"]: i["limit"] for i in body["items"]}["tenders"] == 3
    assert admin.client.get(USAGE).json()["plan_code"] == "starter"
    events = admin.client.get("/api/v1/audit", params={"action": "plan_changed"}).json()["items"]
    assert len(events) == 1
    assert events[0]["entity_type"] == "organisation"
    assert events[0]["metadata"] == {"old_status": "demo", "new_status": "starter"}


@pytest.mark.parametrize("role", ["estimator", "project_manager", "reviewer"])
def test_only_admin_can_switch_plan(admin: Actor, role: str) -> None:
    actor = add_member(admin, f"{role}@example.com", role)
    assert actor.client.put(PLAN, json={"plan_code": "starter"}).status_code == 403
    assert admin.client.get(USAGE).json()["plan_code"] == "demo"


def test_unknown_plan_404_and_bad_body_422(admin: Actor) -> None:
    assert admin.client.put(PLAN, json={"plan_code": "platinum"}).status_code == 404
    assert admin.client.put(PLAN, json={}).status_code == 422
    assert admin.client.put(PLAN, json={"plan_code": "x" * 50}).status_code == 422


def test_other_organisation_plan_is_unaffected(admin: Actor) -> None:
    other = register("b@example.com", org="Org B")
    admin.client.put(PLAN, json={"plan_code": "starter"})
    assert other.client.get(USAGE).json()["plan_code"] == "demo"


def test_available_plans_listed_for_the_switch(admin: Actor) -> None:
    plans = admin.client.get(USAGE).json()["available_plans"]
    assert {p["code"] for p in plans} == {"demo", "starter"}
