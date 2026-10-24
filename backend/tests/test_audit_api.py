"""Audit view: roles, scoping, keyset paging, filters, safe metadata, facets."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.db.session import session_scope
from app.modules.audit.models import AuditEvent
from tests.conftest import Actor, add_member, register

AUDIT = "/api/v1/audit"


def _seed(
    actor: Actor,
    n: int,
    *,
    entity_type: str = "tender",
    action: str = "created",
    user_id: str | None = None,
    start: datetime | None = None,
    metadata: dict | None = None,
    organisation_id: str | None = None,
) -> None:
    base = start or datetime(2026, 1, 1, tzinfo=UTC)
    with session_scope() as s:
        for i in range(n):
            s.add(
                AuditEvent(
                    organisation_id=UUID(organisation_id or actor.org_id),
                    user_id=UUID(user_id or actor.me["user_id"]),
                    entity_type=entity_type,
                    entity_id=uuid4(),
                    action=action,
                    event_metadata=metadata or {},
                    created_at=base + timedelta(seconds=i),
                )
            )


def test_admin_and_project_manager_can_list(admin: Actor) -> None:
    pm = add_member(admin, "pm@example.com", "project_manager")
    assert admin.client.get(AUDIT).status_code == 200
    assert pm.client.get(AUDIT).status_code == 200


def test_estimator_and_reviewer_get_403(admin: Actor) -> None:
    est = add_member(admin, "est@example.com", "estimator")
    rev = add_member(admin, "rev@example.com", "reviewer")
    for actor in (est, rev):
        assert actor.client.get(AUDIT).status_code == 403
        assert actor.client.get(f"{AUDIT}/facets").status_code == 403


def test_unauthenticated_401(client) -> None:
    assert client.get(AUDIT).status_code == 401


def test_newest_first_and_cursor_paging_has_no_gaps_or_duplicates(admin: Actor) -> None:
    with session_scope() as s:
        before = s.query(AuditEvent).count()
    _seed(admin, 60)
    total = before + 60
    seen: list[str] = []
    stamps: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 25, **({"cursor": cursor} if cursor else {})}
        body = admin.client.get(AUDIT, params=params).json()
        pages += 1
        seen += [x["id"] for x in body["items"]]
        stamps += [x["created_at"] for x in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert len(seen) == total and len(set(seen)) == total
    assert pages == -(-total // 25)
    assert stamps == sorted(stamps, reverse=True)


def test_filters_action_entity_type_user_and_dates(admin: Actor) -> None:
    pm = add_member(admin, "pm@example.com", "project_manager")
    day = datetime(2025, 5, 10, 12, tzinfo=UTC)
    _seed(admin, 2, entity_type="estimate", action="approved", start=day)
    _seed(admin, 3, entity_type="tender", action="archived", user_id=pm.me["user_id"], start=day)
    _seed(admin, 1, entity_type="tender", action="archived", start=day + timedelta(days=3))

    def ids(**params):
        r = admin.client.get(AUDIT, params={"limit": 100, **params})
        assert r.status_code == 200, r.text
        return r.json()["items"]

    assert len(ids(action="approved")) == 2
    assert len(ids(entity_type="estimate")) == 2
    assert len(ids(action="archived")) == 4
    assert len(ids(action="archived", user_id=pm.me["user_id"])) == 3
    window = ids(**{"from": "2025-05-10", "to": "2025-05-10"})
    assert len(window) == 5  # the whole of the 10th, inclusive; the 13th is excluded
    assert len(ids(**{"from": "2025-05-13", "to": "2025-05-13"})) == 1


def test_other_organisation_and_null_organisation_events_never_returned(admin: Actor) -> None:
    other = register("b@example.com", org="Org B")
    _seed(other, 3, action="secret-b")
    with session_scope() as s:
        s.add(AuditEvent(organisation_id=None, entity_type="user", action="failed-login"))
    body = admin.client.get(AUDIT, params={"limit": 100}).json()
    actions = {x["action"] for x in body["items"]}
    assert "secret-b" not in actions and "failed-login" not in actions
    facets = admin.client.get(f"{AUDIT}/facets").json()
    assert "secret-b" not in facets["actions"] and "failed-login" not in facets["actions"]


def test_metadata_only_safe_keys(admin: Actor) -> None:
    _seed(admin, 1, action="probe", metadata={"status": "ok", "document_text": "leak", "x": 1})
    items = admin.client.get(AUDIT, params={"action": "probe"}).json()["items"]
    assert items[0]["metadata"] == {"status": "ok"}


def test_user_name_resolved_and_unknown_is_null(admin: Actor) -> None:
    _seed(admin, 1, action="named")
    with session_scope() as s:
        s.add(
            AuditEvent(
                organisation_id=UUID(admin.org_id), user_id=None, entity_type="job", action="sys"
            )
        )
    named = admin.client.get(AUDIT, params={"action": "named"}).json()["items"][0]
    system = admin.client.get(AUDIT, params={"action": "sys"}).json()["items"][0]
    assert named["user_name"] == admin.me["name"]
    assert system["user_name"] is None


def test_bad_cursor_422(admin: Actor) -> None:
    assert admin.client.get(AUDIT, params={"cursor": "not-a-cursor"}).status_code == 422


def test_limit_bounds(admin: Actor) -> None:
    assert admin.client.get(AUDIT, params={"limit": 0}).status_code == 422
    assert admin.client.get(AUDIT, params={"limit": 101}).status_code == 422
    assert admin.client.get(AUDIT, params={"limit": 100}).status_code == 200


def test_facets_distinct_and_scoped(admin: Actor) -> None:
    _seed(admin, 2, entity_type="estimate", action="approved")
    _seed(admin, 2, entity_type="estimate", action="approved")
    facets = admin.client.get(f"{AUDIT}/facets").json()
    assert facets["entity_types"].count("estimate") == 1
    assert facets["actions"].count("approved") == 1
    assert facets["entity_types"] == sorted(facets["entity_types"])
