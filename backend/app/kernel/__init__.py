"""Shared types and errors. No I/O. Must not import fastapi or sqlalchemy."""

from .errors import (
    Conflict,
    DomainError,
    Forbidden,
    JobCancelled,
    LimitExceeded,
    NotFound,
    ProcessingFailed,
    RateLimited,
    Unauthorized,
    ValidationFailed,
)
from .ports import LLMPort, LLMTimeout, LLMUnavailable, StoragePort, StructuredResult
from .types import ROLE_PERMISSIONS, OrgContext, Permission, Role

__all__ = [
    "ROLE_PERMISSIONS",
    "Conflict",
    "DomainError",
    "Forbidden",
    "JobCancelled",
    "LLMPort",
    "LLMTimeout",
    "LLMUnavailable",
    "LimitExceeded",
    "NotFound",
    "OrgContext",
    "Permission",
    "ProcessingFailed",
    "RateLimited",
    "Role",
    "StoragePort",
    "StructuredResult",
    "Unauthorized",
    "ValidationFailed",
]
