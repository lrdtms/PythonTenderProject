"""Identity data access. The only place in this module that talks to the database."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.db.scoped import ScopedRepository
from app.kernel import NotFound

from .models import Membership, Organisation, User, UserSession


class UserRepo:
    def __init__(self, session: Session):
        self.session = session

    def by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(func.lower(User.email) == email.lower()))

    def by_id(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user


class OrganisationRepo:
    def __init__(self, session: Session):
        self.session = session

    def add(self, org: Organisation) -> Organisation:
        self.session.add(org)
        self.session.flush()
        return org

    def get(self, organisation_id: UUID) -> Organisation | None:
        return self.session.get(Organisation, organisation_id)


class SessionRepo:
    def __init__(self, session: Session):
        self.session = session

    def add(self, user_session: UserSession) -> UserSession:
        self.session.add(user_session)
        self.session.flush()
        return user_session

    def active_context(self, token_hash: str) -> tuple[UserSession, Membership, User] | None:
        """The live session, its membership and its user, or None (unknown, expired, revoked,
        deactivated membership or disabled user)."""
        row = self.session.execute(
            select(UserSession, Membership, User)
            .join(
                Membership,
                and_(
                    Membership.organisation_id == UserSession.active_organisation_id,
                    Membership.user_id == UserSession.user_id,
                ),
            )
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > datetime.now(UTC),
                Membership.status == "active",
                User.status == "active",
            )
        ).first()
        return None if row is None else (row[0], row[1], row[2])

    def revoke_by_hash(self, token_hash: str) -> None:
        self.session.execute(
            update(UserSession)
            .where(UserSession.token_hash == token_hash, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    def revoke_for_user(self, user_id: UUID) -> None:
        """Every live session of the user, in every organisation (password reset)."""
        self.session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    def revoke_for_membership(self, organisation_id: UUID, user_id: UUID) -> None:
        self.session.execute(
            update(UserSession)
            .where(
                UserSession.active_organisation_id == organisation_id,
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )


class AccountRepo:
    """Cross-organisation lookups needed before any OrgContext exists (register, login)."""

    def __init__(self, session: Session):
        self.session = session

    def first_active_membership(self, user_id: UUID) -> Membership | None:
        return self.session.scalar(
            select(Membership)
            .where(Membership.user_id == user_id, Membership.status == "active")
            .order_by(Membership.created_at)
        )

    def add_membership(self, membership: Membership) -> Membership:
        self.session.add(membership)
        self.session.flush()
        return membership


class MembershipRepo(ScopedRepository[Membership]):
    model = Membership

    def list_with_users(self) -> list[tuple[Membership, User]]:
        rows = self.session.execute(
            self._select()
            .add_columns(User)
            .join(User, User.id == Membership.user_id)
            .order_by(User.name)
        ).all()
        return [(m, u) for m, u in rows]

    def user_for(self, membership: Membership) -> User:
        user = self.session.get(User, membership.user_id)
        if user is None:
            raise NotFound("User not found")
        return user

    def count_active_admins(self) -> int:
        """Count this organisation's active admins, locking their rows (FOR UPDATE) so two
        concurrent demotions cannot both see two admins and remove the last one."""
        stmt = (
            self._select()
            .where(Membership.role == "admin", Membership.status == "active")
            .with_for_update()
        )
        return len(self.session.scalars(stmt).all())
