"""Shared types and errors. No I/O. Must not import fastapi or sqlalchemy."""

from .errors import (
    Conflict,
    DomainError,
    Forbidden,
    LimitExceeded,
    NotFound,
    RateLimited,
    Unauthorized,
    ValidationFailed,
)
from .types import ROLE_PERMISSIONS, OrgContext, Permission, Role

__all__ = [
    "ROLE_PERMISSIONS",
    "Conflict",
    "DomainError",
    "Forbidden",
    "LimitExceeded",
    "NotFound",
    "OrgContext",
    "Permission",
    "RateLimited",
    "Role",
    "Unauthorized",
    "ValidationFailed",
]
