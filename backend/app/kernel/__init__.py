"""Shared types and errors. No I/O. Must not import fastapi or sqlalchemy."""

from .errors import (
    Conflict,
    DomainError,
    Forbidden,
    LimitExceeded,
    NotFound,
    ProcessingFailed,
    RateLimited,
    Unauthorized,
    ValidationFailed,
)
from .ports import StoragePort
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
    "ProcessingFailed",
    "RateLimited",
    "Role",
    "StoragePort",
    "Unauthorized",
    "ValidationFailed",
]
