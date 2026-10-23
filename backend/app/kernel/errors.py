"""Domain errors. The API layer maps these to HTTP responses."""

from __future__ import annotations


class DomainError(Exception):
    code = "error"

    def __init__(
        self, message: str = "", details: object | None = None, *, code: str | None = None
    ):
        if code is not None:
            self.code = code
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


class ProcessingFailed(Exception):
    """A document-processing failure. `error_code` is a short stable code (never document text);
    transient failures are retried by the queue, permanent ones are not."""

    def __init__(self, error_code: str, message: str = "", *, transient: bool = False):
        super().__init__(message or error_code)
        self.error_code = error_code
        self.transient = transient


class JobCancelled(Exception):
    """Raised inside a running job when it was cancelled: the worker stops without recording a
    failure, and the handler's uncommitted work is rolled back."""
