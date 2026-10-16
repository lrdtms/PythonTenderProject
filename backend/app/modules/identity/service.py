"""Identity use cases: registration, login, sessions, member management."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import (
    ROLE_PERMISSIONS,
    Conflict,
    NotFound,
    OrgContext,
    Permission,
    Role,
    Unauthorized,
    ValidationFailed,
)
from app.modules.audit import public as audit

from . import passwords
from .models import Membership, Organisation, User, UserSession
from .repo import AccountRepo, MembershipRepo, OrganisationRepo, SessionRepo, UserRepo
from .schemas import MeDTO, MemberDTO

SESSION_LIFETIME = timedelta(hours=24)
INVALID_LOGIN = "Invalid email or password."


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_session(session: Session, user_id: UUID, organisation_id: UUID) -> str:
    token = secrets.token_urlsafe(32)
    SessionRepo(session).add(
        UserSession(
            token_hash=hash_token(token),
            user_id=user_id,
            active_organisation_id=organisation_id,
            expires_at=datetime.now(UTC) + SESSION_LIFETIME,
        )
    )
    return token


def register_organisation(
    session: Session, organisation_name: str, name: str, email: str, password: str
) -> tuple[str, OrgContext]:
    """Create an organisation with its first admin and log them in. Returns (session token, ctx)."""
    email = email.strip().lower()
    passwords.check_policy(password, email)
    if UserRepo(session).by_email(email):
        raise Conflict("An account with this email already exists.", {"field": "email"})
    org = OrganisationRepo(session).add(
        Organisation(name=organisation_name.strip(), contact_email=email)
    )
    user = UserRepo(session).add(
        User(email=email, name=name.strip(), password_hash=passwords.hash_password(password))
    )
    membership = AccountRepo(session).add_membership(
        Membership(organisation_id=org.id, user_id=user.id, role=Role.ADMIN.value)
    )
    ctx = OrgContext(user.id, org.id, Role.ADMIN, membership.id)
    audit.record(session, ctx, "organisation", org.id, "registered")
    token = _new_session(session, user.id, org.id)
    return token, ctx


def login(session: Session, email: str, password: str) -> tuple[str, OrgContext]:
    email = email.strip().lower()
    user = UserRepo(session).by_email(email)
    ok = passwords.verify_password(password, user.password_hash if user else None)
    membership = AccountRepo(session).first_active_membership(user.id) if user and ok else None
    if not (user and ok and user.status == "active" and membership):
        audit.record(
            session, None, "session", None, "login_failed",
            {"reason": "invalid_credentials"}, user_id=user.id if user else None,
        )  # fmt: skip
        # Commit the audit row even though the request fails.
        session.commit()
        raise Unauthorized(INVALID_LOGIN)
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)  # upgrade to current parameters
    ctx = OrgContext(user.id, membership.organisation_id, Role(membership.role), membership.id)
    audit.record(session, ctx, "session", None, "login")
    return _new_session(session, user.id, membership.organisation_id), ctx


def resolve_context(session: Session, token: str | None) -> OrgContext:
    """Build the OrgContext from the session cookie and a live database membership lookup."""
    if not token:
        raise Unauthorized("Not signed in.")
    found = SessionRepo(session).active_context(hash_token(token))
    if found is None:
        raise Unauthorized("Not signed in.")
    _, membership, user = found
    return OrgContext(user.id, membership.organisation_id, Role(membership.role), membership.id)


def logout(session: Session, token: str | None, ctx: OrgContext | None = None) -> None:
    if token:
        SessionRepo(session).revoke_by_hash(hash_token(token))
    if ctx:
        audit.record(session, ctx, "session", None, "logout")


def me(session: Session, ctx: OrgContext) -> MeDTO:
    user = UserRepo(session).by_id(ctx.user_id)
    org = OrganisationRepo(session).get(ctx.organisation_id)
    if user is None or org is None:
        raise NotFound("Account not found")
    return MeDTO(
        user_id=user.id, name=user.name, email=user.email, organisation_id=org.id,
        organisation_name=org.name, role=ctx.role,
        permissions=sorted(p.value for p in ROLE_PERMISSIONS[ctx.role]),
    )  # fmt: skip


# --- members (admin only) --------------------------------------------------------------------


def _member_dto(m: Membership, u: User) -> MemberDTO:
    return MemberDTO(
        membership_id=m.id,
        user_id=u.id,
        name=u.name,
        email=u.email,
        role=Role(m.role),
        status=m.status,
    )


def list_members(session: Session, ctx: OrgContext) -> list[MemberDTO]:
    ctx.require(Permission.MANAGE_MEMBERS)
    return [_member_dto(m, u) for m, u in MembershipRepo(session, ctx).list_with_users()]


def create_member(
    session: Session, ctx: OrgContext, name: str, email: str, role: Role, password: str
) -> MemberDTO:
    ctx.require(Permission.MANAGE_MEMBERS)
    email = email.strip().lower()
    passwords.check_policy(password, email)
    if UserRepo(session).by_email(email):
        raise Conflict("An account with this email already exists.", {"field": "email"})
    user = UserRepo(session).add(
        User(email=email, name=name.strip(), password_hash=passwords.hash_password(password))
    )
    membership = MembershipRepo(session, ctx).add(
        Membership(user_id=user.id, role=role.value)  # organisation_id is stamped by the repo
    )
    audit.record(session, ctx, "membership", membership.id, "member_created",
                 {"role": role.value, "target_user_id": str(user.id)})  # fmt: skip
    return _member_dto(membership, user)


def _target(
    session: Session, ctx: OrgContext, membership_id: UUID
) -> tuple[MembershipRepo, Membership]:
    repo = MembershipRepo(session, ctx)
    return repo, repo.get(membership_id)  # NotFound for another organisation's membership


def change_role(session: Session, ctx: OrgContext, membership_id: UUID, role: Role) -> MemberDTO:
    ctx.require(Permission.MANAGE_MEMBERS)
    repo, membership = _target(session, ctx, membership_id)
    if (
        membership.role == Role.ADMIN.value
        and membership.status == "active"
        and role != Role.ADMIN
        and repo.count_active_admins() <= 1
    ):
        raise ValidationFailed("An organisation needs at least one active admin.")
    old = membership.role
    membership.role = role.value
    audit.record(session, ctx, "membership", membership.id, "role_changed",
                 {"old_role": old, "new_role": role.value})  # fmt: skip
    return _member_dto(membership, repo.user_for(membership))


def set_member_status(
    session: Session, ctx: OrgContext, membership_id: UUID, active: bool
) -> MemberDTO:
    ctx.require(Permission.MANAGE_MEMBERS)
    repo, membership = _target(session, ctx, membership_id)
    if (
        not active
        and membership.role == Role.ADMIN.value
        and membership.status == "active"
        and repo.count_active_admins() <= 1
    ):
        raise ValidationFailed("An organisation needs at least one active admin.")
    membership.status = "active" if active else "deactivated"
    if not active:
        SessionRepo(session).revoke_for_membership(membership.organisation_id, membership.user_id)
    audit.record(session, ctx, "membership", membership.id,
                 "member_reactivated" if active else "member_deactivated")  # fmt: skip
    return _member_dto(membership, repo.user_for(membership))


def reset_member_password(
    session: Session, ctx: OrgContext, membership_id: UUID, password: str
) -> None:
    ctx.require(Permission.MANAGE_MEMBERS)
    repo, membership = _target(session, ctx, membership_id)
    user = repo.user_for(membership)
    passwords.check_policy(password, user.email)
    user.password_hash = passwords.hash_password(password)
    # The password is global to the user, so every session goes, not only this organisation's.
    SessionRepo(session).revoke_for_user(membership.user_id)
    audit.record(session, ctx, "membership", membership.id, "password_reset")


def member_names(session: Session, ctx: OrgContext, user_ids: Collection[UUID]) -> dict[UUID, str]:
    ctx.require(Permission.READ)
    return MembershipRepo(session, ctx).names_for(set(user_ids))
