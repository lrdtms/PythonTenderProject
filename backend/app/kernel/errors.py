"""Domain errors. The API layer maps these to HTTP responses."""

from __future__ import annotations


class DomainError(Exception):
    code = "error"

    def __init__(self, message: str = "", details: object | None = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details


class Unauthorized(DomainError):
    code = "unauthorized"


class Forbidden(DomainError):
    code = "forbidden"


class NotFound(DomainError):
    """Also used for rows that belong to another organisation (no existence oracle)."""

    code = "not_found"


class Conflict(DomainError):
    code = "conflict"


class ValidationFailed(DomainError):
    code = "validation_error"


class LimitExceeded(DomainError):
    code = "limit_exceeded"


class RateLimited(DomainError):
    code = "rate_limited"
