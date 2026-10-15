from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.db.session import session_scope
from app.modules.audit.models import AuditEvent
from app.modules.identity.models import UserSession
from tests.conftest import CSRF, STRONG_PASSWORD, make_client


def test_register_logs_in_and_sets_a_safe_cookie(client) -> None:
    r = client.post(
        "/api/v1/auth/register",
        json={"organisation_name": "Acme", "name": "Ann", "email": "ann@example.com",
              "password": STRONG_PASSWORD},
    )  # fmt: skip
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "admin" and "manage_members" in body["permissions"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api" in cookie
    assert client.get("/api/v1/me").json()["email"] == "ann@example.com"


def test_session_token_is_stored_hashed(admin) -> None:
    token = admin.client.cookies.get("intel_session")
    with session_scope() as s:
        hashes = s.scalars(select(UserSession.token_hash)).all()
    assert token and token not in hashes and len(hashes[0]) == 64


def test_duplicate_email_is_a_conflict(admin) -> None:
    r = make_client().post(
        "/api/v1/auth/register",
        json={"organisation_name": "Other", "name": "X", "email": "OWNER@example.com",
              "password": STRONG_PASSWORD},
    )  # fmt: skip
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


def test_weak_password_rejected_without_echoing_it(client) -> None:
    r = client.post(
        "/api/v1/auth/register",
        json={
            "organisation_name": "Acme",
            "name": "Ann",
            "email": "ann@example.com",
            "password": "short",
        },
    )
    assert r.status_code == 422 and "short" not in r.text.replace("shorter", "")
    assert r.json()["error"]["code"] == "validation_error"


def test_validation_errors_never_echo_input(client) -> None:
    r = client.post(
        "/api/v1/auth/login", json={"email": "not-an-email", "password": "secret-value-123"}
    )
    assert r.status_code == 422 and "secret-value-123" not in r.text


def test_login_failures_are_indistinguishable(admin) -> None:
    c = make_client()
    unknown = c.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": STRONG_PASSWORD}
    )
    wrong = c.post(
        "/api/v1/auth/login", json={"email": "owner@example.com", "password": "wrong-password-1"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_failed_login_is_audited_and_session_is_not_created(admin) -> None:
    make_client().post(
        "/api/v1/auth/login", json={"email": "owner@example.com", "password": "wrong-password-1"}
    )
    with session_scope() as s:
        actions = s.scalars(select(AuditEvent.action)).all()
        sessions = s.scalars(select(UserSession)).all()
    assert "login_failed" in actions and len(sessions) == 1  # only the registration session


def test_login_is_rate_limited(admin) -> None:
    c = make_client()
    codes = [
        c.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "wrong-password-1"},
        ).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


def test_logout_revokes_the_session(admin) -> None:
    assert admin.client.post("/api/v1/auth/logout").status_code == 204
    assert admin.client.get("/api/v1/me").status_code == 401


def test_expired_session_is_rejected(admin) -> None:
    with session_scope() as s:
        s.execute(update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    assert admin.client.get("/api/v1/me").status_code == 401


def test_protected_routes_require_a_session(client) -> None:
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/tenders").status_code == 401
    assert client.get("/api/v1/members").status_code == 401


def test_state_changing_requests_need_the_csrf_header(admin) -> None:
    no_header = make_client()
    no_header.headers.pop("X-Requested-With")
    no_header.cookies.update(admin.client.cookies)
    r = no_header.post("/api/v1/tenders", json={"title": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    assert (
        admin.client.post("/api/v1/tenders", json={"title": "x"}, headers=CSRF).status_code == 201
    )


# --- rate limiting (review I-2) ------------------------------------------------------------------


def _wrong_login(c, email: str = "owner@example.com", headers: dict | None = None) -> int:
    return c.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-password-1"},
        headers=headers or {},
    ).status_code


def test_rotating_x_forwarded_for_does_not_escape_the_login_limit(admin) -> None:
    c = make_client()
    codes = [_wrong_login(c, headers={"X-Forwarded-For": f"10.0.0.{i}"}) for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


def test_spraying_one_password_across_many_emails_is_limited_per_ip(admin) -> None:
    c = make_client()
    codes = [_wrong_login(c, email=f"user{i}@example.com") for i in range(40)]
    assert codes[:30] == [401] * 30 and set(codes[30:]) == {429}


def test_the_configured_client_ip_header_is_honoured(admin, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "client_ip_header", "CF-Connecting-IP")
    c = make_client()
    first = [_wrong_login(c, headers={"CF-Connecting-IP": "203.0.113.1"}) for _ in range(11)]
    assert first[:10] == [401] * 10 and first[10] == 429
    # Another visitor behind the same proxy has their own bucket.
    assert _wrong_login(c, headers={"CF-Connecting-IP": "203.0.113.2"}) == 401


def test_register_is_rate_limited(client) -> None:
    codes = [
        client.post(
            "/api/v1/auth/register",
            json={"organisation_name": f"Org {i}", "name": "N", "email": f"r{i}@example.com",
                  "password": STRONG_PASSWORD},
        ).status_code
        for i in range(6)
    ]  # fmt: skip
    assert codes == [201] * 5 + [429]


def test_member_creation_is_rate_limited_per_organisation(admin) -> None:
    # Probing addresses with an existing email (409) still counts toward the limit.
    body = {"name": "X", "email": "owner@example.com", "role": "reviewer",
            "password": STRONG_PASSWORD}  # fmt: skip
    codes = [admin.client.post("/api/v1/members", json=body).status_code for _ in range(21)]
    assert codes == [409] * 20 + [429]


# --- secure cookie (review I-3) ------------------------------------------------------------------


def _register_cookie(client) -> str:
    r = client.post(
        "/api/v1/auth/register",
        json={"organisation_name": "Acme", "name": "Ann", "email": "ann@example.com",
              "password": STRONG_PASSWORD},
    )  # fmt: skip
    assert r.status_code == 201
    return r.headers["set-cookie"].lower()


def test_cookie_secure_defaults_to_on() -> None:
    from app.config import Settings

    assert Settings.model_fields["cookie_secure"].default is True


def test_session_cookie_is_secure_when_the_setting_is_on(client, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "cookie_secure", True)
    assert "secure" in _register_cookie(client)


def test_session_cookie_is_not_secure_when_the_setting_is_off(client, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "cookie_secure", False)
    assert "secure" not in _register_cookie(client)


# --- small items (review minors) -----------------------------------------------------------------


def test_login_upgrades_an_outdated_password_hash(admin, monkeypatch) -> None:
    from argon2 import PasswordHasher

    from app.modules.identity import passwords
    from app.modules.identity.models import User

    with session_scope() as s:
        before = s.scalar(select(User.password_hash))
    stronger = PasswordHasher(time_cost=passwords._hasher.time_cost + 1)
    monkeypatch.setattr(passwords, "_hasher", stronger)
    r = make_client().post(
        "/api/v1/auth/login", json={"email": "owner@example.com", "password": STRONG_PASSWORD}
    )
    assert r.status_code == 200
    with session_scope() as s:
        after = s.scalar(select(User.password_hash))
    assert after != before and not stronger.check_needs_rehash(after)
    assert stronger.verify(after, STRONG_PASSWORD)


def test_patch_and_logout_need_the_csrf_header(admin) -> None:
    tid = admin.client.post("/api/v1/tenders", json={"title": "T"}).json()["id"]
    no_header = make_client()
    no_header.headers.pop("X-Requested-With")
    no_header.cookies.update(admin.client.cookies)
    patch = no_header.patch(f"/api/v1/tenders/{tid}", json={"title": "changed"})
    assert patch.status_code == 403 and patch.json()["error"]["code"] == "csrf_failed"
    logout = no_header.post("/api/v1/auth/logout")
    assert logout.status_code == 403 and logout.json()["error"]["code"] == "csrf_failed"
    # Neither went through: the title is unchanged and the session is still live.
    assert admin.client.get(f"/api/v1/tenders/{tid}").json()["title"] == "T"
    assert admin.client.get("/api/v1/me").status_code == 200


def test_member_actions_and_login_are_audited(admin) -> None:
    from tests.conftest import add_member

    add_member(admin, "est@example.com", "estimator")  # logs in as the new member
    mid = next(
        m["membership_id"]
        for m in admin.client.get("/api/v1/members").json()
        if m["email"] == "est@example.com"
    )
    admin.client.patch(f"/api/v1/members/{mid}/role", json={"role": "reviewer"})
    admin.client.post(f"/api/v1/members/{mid}/reset-password", json={"password": "another-pass-1"})
    admin.client.post(f"/api/v1/members/{mid}/deactivate")
    with session_scope() as s:
        events = s.scalars(select(AuditEvent).order_by(AuditEvent.created_at)).all()
    by_action = {e.action: e for e in events}
    for action in ("login", "role_changed", "password_reset", "member_deactivated"):
        assert action in by_action, action
        assert by_action[action].organisation_id is not None
    assert by_action["role_changed"].event_metadata == {
        "old_role": "estimator",
        "new_role": "reviewer",
    }
    assert "another-pass-1" not in str([e.event_metadata for e in events])


def test_get_ctx_sets_the_transaction_local_org_id(admin) -> None:
    from sqlalchemy import text
    from starlette.requests import Request

    from app.api.deps import SESSION_COOKIE, get_ctx

    token = admin.client.cookies.get(SESSION_COOKIE)
    request = Request(
        {"type": "http", "headers": [(b"cookie", f"{SESSION_COOKIE}={token}".encode())]}
    )
    setting = text("SELECT current_setting('app.org_id', true)")
    with session_scope() as s:
        assert not s.scalar(setting)
        ctx = get_ctx(request, s)
        assert s.scalar(setting) == str(ctx.organisation_id) == admin.org_id
        s.commit()
        assert not s.scalar(setting)  # transaction-local: gone after the commit
