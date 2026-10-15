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
