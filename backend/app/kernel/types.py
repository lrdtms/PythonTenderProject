"""Shared types. No I/O, no framework imports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from .errors import Forbidden


class Role(StrEnum):
    ADMIN = "admin"
    ESTIMATOR = "estimator"
    PROJECT_MANAGER = "project_manager"
    REVIEWER = "reviewer"


class Permission(StrEnum):
    READ = "read"
    MANAGE_MEMBERS = "manage_members"
    EDIT_TENDERS = "edit_tenders"
    UPLOAD_DOCUMENTS = "upload_documents"
    REVIEW_DATA = "review_data"
    MANAGE_TASKS = "manage_tasks"
    EXPORT = "export"
    VIEW_AUDIT = "view_audit"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.ESTIMATOR: frozenset(
        {
            Permission.READ,
            Permission.EDIT_TENDERS,
            Permission.UPLOAD_DOCUMENTS,
            Permission.REVIEW_DATA,
            Permission.MANAGE_TASKS,
            Permission.EXPORT,
        }
    ),
    Role.PROJECT_MANAGER: frozenset(
        {
            Permission.READ,
            Permission.EDIT_TENDERS,
            Permission.MANAGE_TASKS,
            Permission.EXPORT,
            Permission.VIEW_AUDIT,
        }
    ),
    Role.REVIEWER: frozenset({Permission.READ}),
}


@dataclass(frozen=True)
class OrgContext:
    """Who is acting, in which organisation, with which role. Built on the server from the
    session and a database membership lookup. Never built from request paths or bodies."""

    user_id: UUID
    organisation_id: UUID
    role: Role
    membership_id: UUID | None = None

    @classmethod
    def system(cls, organisation_id: UUID, user_id: UUID) -> OrgContext:
        """The context a worker uses for a job. Built from the job row, never from document
        content. Acts with full rights inside that one organisation only."""
        return cls(user_id, organisation_id, Role.ADMIN, None)

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]

    def require(self, permission: Permission) -> None:
        if not self.can(permission):
            raise Forbidden("You do not have permission to do this.")
