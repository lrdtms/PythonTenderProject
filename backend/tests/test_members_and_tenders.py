from sqlalchemy import select

from app.db.session import session_scope
from app.modules.audit.models import AuditEvent
from tests.conftest import STRONG_PASSWORD, add_member, make_client, register


def member_id(admin, email: str) -> str:
    members = admin.client.get("/api/v1/members").json()
    return next(m["membership_id"] for m in members if m["email"] == email)


# --- members -----------------------------------------------------------------------------------


def test_admin_creates_a_member_who_can_log_in(admin) -> None:
    est = add_member(admin, "est@example.com", "estimator")
    assert est.me["role"] == "estimator" and est.me["organisation_id"] == admin.org_id
    assert len(admin.client.get("/api/v1/members").json()) == 2


def test_non_admins_cannot_manage_members(admin) -> None:
    est = add_member(admin, "est@example.com", "estimator")
    rev = add_member(admin, "rev@example.com", "reviewer")
    for actor in (est, rev):
        assert actor.client.get("/api/v1/members").status_code == 403
        r = actor.client.post(
            "/api/v1/members",
            json={
                "name": "X",
                "email": "x@example.com",
                "role": "admin",
                "password": STRONG_PASSWORD,
            },
        )
        assert r.status_code == 403


def test_role_change_takes_effect_immediately(admin) -> None:
    est = add_member(admin, "est@example.com", "estimator")
    assert est.client.post("/api/v1/tenders", json={"title": "T1"}).status_code == 201
    mid = member_id(admin, "est@example.com")
    assert (
        admin.client.patch(f"/api/v1/members/{mid}/role", json={"role": "reviewer"}).status_code
        == 200
    )
    # Same session cookie, no re-login: the role is read from the database on every request.
    assert est.client.post("/api/v1/tenders", json={"title": "T2"}).status_code == 403
    assert est.client.get("/api/v1/tenders").status_code == 200


def test_cannot_demote_or_deactivate_the_last_admin(admin) -> None:
    mid = member_id(admin, "owner@example.com")
    assert (
        admin.client.patch(f"/api/v1/members/{mid}/role", json={"role": "reviewer"}).status_code
        == 422
    )
    assert admin.client.post(f"/api/v1/members/{mid}/deactivate").status_code == 422


def test_deactivation_revokes_access_immediately(admin) -> None:
    est = add_member(admin, "est@example.com", "estimator")
    mid = member_id(admin, "est@example.com")
    assert admin.client.post(f"/api/v1/members/{mid}/deactivate").status_code == 200
    assert est.client.get("/api/v1/me").status_code == 401
    relog = make_client().post(
        "/api/v1/auth/login", json={"email": "est@example.com", "password": STRONG_PASSWORD}
    )
    assert relog.status_code == 401
    assert admin.client.post(f"/api/v1/members/{mid}/reactivate").status_code == 200
    again = make_client().post(
        "/api/v1/auth/login", json={"email": "est@example.com", "password": STRONG_PASSWORD}
    )
    assert again.status_code == 200


def test_password_reset_revokes_sessions_and_changes_the_password(admin) -> None:
    est = add_member(admin, "est@example.com", "estimator")
    mid = member_id(admin, "est@example.com")
    r = admin.client.post(
        f"/api/v1/members/{mid}/reset-password", json={"password": "another-strong-pass"}
    )
    assert r.status_code == 204
    assert est.client.get("/api/v1/me").status_code == 401
    old = make_client().post(
        "/api/v1/auth/login", json={"email": "est@example.com", "password": STRONG_PASSWORD}
    )
    new = make_client().post(
        "/api/v1/auth/login", json={"email": "est@example.com", "password": "another-strong-pass"}
    )
    assert old.status_code == 401 and new.status_code == 200


# --- tenders -----------------------------------------------------------------------------------


def test_tender_lifecycle(admin) -> None:
    c = admin.client
    created = c.post(
        "/api/v1/tenders",
        json={"title": "Hall wiring", "reference_number": "GV/ELEC/2026/014", "client_name": "Greenvale",
              "closing_at": "2026-11-27T11:00:00+02:00"},
    )  # fmt: skip
    assert created.status_code == 201
    tid = created.json()["id"]
    assert (
        created.json()["status"] == "preparing"
        and created.json()["created_by"] == admin.me["user_id"]
    )

    assert c.get(f"/api/v1/tenders/{tid}").json()["title"] == "Hall wiring"
    upd = c.patch(f"/api/v1/tenders/{tid}", json={"location": "Greenvale", "status": "in_review"})
    assert upd.status_code == 200 and upd.json()["location"] == "Greenvale"

    assert c.patch(f"/api/v1/tenders/{tid}", json={"status": "bogus"}).status_code == 422
    assert c.patch(f"/api/v1/tenders/{tid}", json={"title": ""}).status_code == 422

    arch = c.post(f"/api/v1/tenders/{tid}/archive")
    assert arch.json()["status"] == "archived" and arch.json()["archived_at"]
    assert c.get("/api/v1/tenders").json() == []
    assert len(c.get("/api/v1/tenders?include_archived=true").json()) == 1


def test_reviewer_can_read_but_not_write(admin) -> None:
    tid = admin.client.post("/api/v1/tenders", json={"title": "T"}).json()["id"]
    rev = add_member(admin, "rev@example.com", "reviewer")
    assert rev.client.get(f"/api/v1/tenders/{tid}").status_code == 200
    assert rev.client.post("/api/v1/tenders", json={"title": "X"}).status_code == 403
    assert rev.client.patch(f"/api/v1/tenders/{tid}", json={"title": "X"}).status_code == 403
    assert rev.client.post(f"/api/v1/tenders/{tid}/archive").status_code == 403


def test_tenders_are_invisible_to_other_organisations(admin) -> None:
    tid = admin.client.post("/api/v1/tenders", json={"title": "Secret bid"}).json()["id"]
    other = register("other@example.com", org="Other Co")
    assert other.client.get("/api/v1/tenders").json() == []
    r = other.client.get(f"/api/v1/tenders/{tid}")
    assert r.status_code == 404 and "Secret bid" not in r.text
    assert other.client.patch(f"/api/v1/tenders/{tid}", json={"title": "pwned"}).status_code == 404
    assert admin.client.get(f"/api/v1/tenders/{tid}").json()["title"] == "Secret bid"


def test_unknown_ids_and_malformed_ids_are_handled(admin) -> None:
    assert (
        admin.client.get("/api/v1/tenders/00000000-0000-0000-0000-000000000000").status_code == 404
    )
    assert admin.client.get("/api/v1/tenders/not-a-uuid").status_code == 422


def test_audit_events_are_written_with_safe_metadata(admin) -> None:
    tid = admin.client.post("/api/v1/tenders", json={"title": "Top secret title"}).json()["id"]
    admin.client.patch(f"/api/v1/tenders/{tid}", json={"status": "ready"})
    with session_scope() as s:
        events = s.scalars(select(AuditEvent).where(AuditEvent.entity_type == "tender")).all()
    assert [e.action for e in events] == ["created", "updated"]
    assert all("Top secret title" not in str(e.event_metadata) for e in events)
    assert events[1].event_metadata["new_status"] == "ready"


def test_patch_with_null_title_or_status_is_a_validation_error(admin) -> None:
    c = admin.client
    tid = c.post("/api/v1/tenders", json={"title": "T", "location": "Here"}).json()["id"]
    for field in ("title", "status"):
        r = c.patch(f"/api/v1/tenders/{tid}", json={field: None})
        assert r.status_code == 422, (field, r.status_code)
        assert r.json()["error"]["code"] == "validation_error"
    # Optional fields can still be cleared.
    cleared = c.patch(f"/api/v1/tenders/{tid}", json={"location": None})
    assert cleared.status_code == 200 and cleared.json()["location"] is None


def test_an_archived_tender_can_only_be_reopened(admin) -> None:
    c = admin.client
    tid = c.post("/api/v1/tenders", json={"title": "Old bid"}).json()["id"]
    assert c.post(f"/api/v1/tenders/{tid}/archive").status_code == 200
    for body in ({"title": "Edited"}, {"location": "X"}, {"status": "ready", "title": "Edited"}):
        r = c.patch(f"/api/v1/tenders/{tid}", json=body)
        assert r.status_code == 409, (body, r.status_code)
    assert c.post(f"/api/v1/tenders/{tid}/archive").status_code == 409  # already archived
    assert c.get(f"/api/v1/tenders/{tid}").json()["title"] == "Old bid"
    reopened = c.patch(f"/api/v1/tenders/{tid}", json={"status": "preparing"})
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "preparing" and reopened.json()["archived_at"] is None
    assert c.patch(f"/api/v1/tenders/{tid}", json={"title": "Edited"}).status_code == 200


# --- one user, one organisation; password reset (review I-7) -----------------------------------


def test_create_member_rejects_an_email_that_exists_in_another_organisation(admin) -> None:
    other = register("other@example.com", org="Other Co")
    r = admin.client.post(
        "/api/v1/members",
        json={"name": "X", "email": "OTHER@example.com", "role": "reviewer",
              "password": STRONG_PASSWORD},
    )  # fmt: skip
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    assert [m["email"] for m in other.client.get("/api/v1/members").json()] == ["other@example.com"]


def test_password_reset_revokes_every_session_of_the_user(admin) -> None:
    from datetime import UTC, datetime, timedelta
    from uuid import UUID

    from app.modules.identity.models import Membership, UserSession

    est = add_member(admin, "est@example.com", "estimator")
    make_client().post(  # a second session in the same organisation
        "/api/v1/auth/login", json={"email": "est@example.com", "password": STRONG_PASSWORD}
    )
    other = register("other@example.com", org="Other Co")
    user_id = UUID(est.me["user_id"])
    # Guard the invariant even if a user ever gets a second membership: seed one directly.
    with session_scope() as s:
        s.add(Membership(organisation_id=UUID(other.org_id), user_id=user_id, role="reviewer"))
        s.flush()
        s.add(
            UserSession(
                token_hash="f" * 64,
                user_id=user_id,
                active_organisation_id=UUID(other.org_id),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    mid = member_id(admin, "est@example.com")
    r = admin.client.post(
        f"/api/v1/members/{mid}/reset-password", json={"password": "another-strong-pass"}
    )
    assert r.status_code == 204
    with session_scope() as s:
        sessions = s.scalars(select(UserSession).where(UserSession.user_id == user_id)).all()
    assert len(sessions) == 3 and all(x.revoked_at is not None for x in sessions)


# --- last-admin rule (review minor) -------------------------------------------------------------


def test_a_deactivated_admin_can_be_demoted_or_deactivated_again(admin) -> None:
    add_member(admin, "admin2@example.com", "admin")
    mid = member_id(admin, "admin2@example.com")
    assert admin.client.post(f"/api/v1/members/{mid}/deactivate").status_code == 200
    # One active admin remains; the target is not active, so the rule does not apply.
    assert admin.client.post(f"/api/v1/members/{mid}/deactivate").status_code == 200
    r = admin.client.patch(f"/api/v1/members/{mid}/role", json={"role": "reviewer"})
    assert r.status_code == 200 and r.json()["role"] == "reviewer"
    # The last active admin is still protected.
    own = member_id(admin, "owner@example.com")
    assert (
        admin.client.patch(f"/api/v1/members/{own}/role", json={"role": "reviewer"}).status_code
        == 422
    )
