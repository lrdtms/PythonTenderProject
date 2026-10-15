"""Registration, login, logout and the current user."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.deps import SESSION_COOKIE, Ctx, DbSession
from app.api.ratelimit import client_ip, limiter
from app.config import get_settings
from app.modules.identity import public as identity
from app.modules.identity.service import SESSION_LIFETIME

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=get_settings().environment != "development",
        path="/api",
    )


@router.post("/auth/register", response_model=identity.MeDTO, status_code=201)
def register(
    body: identity.RegisterRequest, request: Request, response: Response, session: DbSession
):
    limiter.check(f"register:{client_ip(request)}", limit=5, window_seconds=3600)
    token, ctx = identity.register_organisation(
        session, body.organisation_name, body.name, body.email, body.password
    )
    _set_cookie(response, token)
    return identity.me(session, ctx)


@router.post("/auth/login", response_model=identity.MeDTO)
def login(body: identity.LoginRequest, request: Request, response: Response, session: DbSession):
    limiter.check(f"login:{client_ip(request)}:{body.email.lower()}", limit=10, window_seconds=300)
    token, ctx = identity.login(session, body.email, body.password)
    _set_cookie(response, token)
    return identity.me(session, ctx)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, session: DbSession) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    try:
        ctx = identity.resolve_context(session, token)
    except Exception:  # noqa: BLE001 - logging out when already signed out is fine
        ctx = None
    identity.logout(session, token, ctx)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/api")
    return response


@router.get("/me", response_model=identity.MeDTO)
def get_me(ctx: Ctx, session: DbSession):
    return identity.me(session, ctx)
