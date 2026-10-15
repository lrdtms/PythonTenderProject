"""Member management (admin only; enforced in the service)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

from app.api.deps import Ctx, DbSession
from app.api.ratelimit import limiter
from app.modules.identity import public as identity

router = APIRouter(prefix="/api/v1/members", tags=["members"])


@router.get("", response_model=list[identity.MemberDTO])
def list_members(ctx: Ctx, session: DbSession):
    return identity.list_members(session, ctx)


@router.post("", response_model=identity.MemberDTO, status_code=201)
def create_member(body: identity.CreateMemberRequest, ctx: Ctx, session: DbSession):
    # Per organisation, so the endpoint cannot be used to probe which emails have accounts.
    limiter.check(f"members:{ctx.organisation_id}", limit=20, window_seconds=3600)
    return identity.create_member(session, ctx, body.name, body.email, body.role, body.password)


@router.patch("/{membership_id}/role", response_model=identity.MemberDTO)
def change_role(
    membership_id: UUID, body: identity.ChangeRoleRequest, ctx: Ctx, session: DbSession
):
    return identity.change_role(session, ctx, membership_id, body.role)


@router.post("/{membership_id}/deactivate", response_model=identity.MemberDTO)
def deactivate(membership_id: UUID, ctx: Ctx, session: DbSession):
    return identity.set_member_status(session, ctx, membership_id, active=False)


@router.post("/{membership_id}/reactivate", response_model=identity.MemberDTO)
def reactivate(membership_id: UUID, ctx: Ctx, session: DbSession):
    return identity.set_member_status(session, ctx, membership_id, active=True)


@router.post("/{membership_id}/reset-password", status_code=204)
def reset_password(
    membership_id: UUID, body: identity.ResetPasswordRequest, ctx: Ctx, session: DbSession
) -> Response:
    identity.reset_member_password(session, ctx, membership_id, body.password)
    return Response(status_code=204)
