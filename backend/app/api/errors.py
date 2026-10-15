"""One consistent error format: {"error": {"code", "message", "details"?}}."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.kernel import (
    Conflict,
    DomainError,
    Forbidden,
    LimitExceeded,
    NotFound,
    RateLimited,
    Unauthorized,
    ValidationFailed,
)

log = logging.getLogger("api")

STATUS = {
    Unauthorized: 401,
    Forbidden: 403,
    NotFound: 404,
    Conflict: 409,
    ValidationFailed: 422,
    LimitExceeded: 403,
    RateLimited: 429,
}


def error_body(code: str, message: str, details: object | None = None) -> dict:
    body: dict = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        status = next((s for cls, s in STATUS.items() if isinstance(exc, cls)), 400)
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo `input`: it can contain passwords.
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            error_body("validation_error", "The request is not valid.", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(error_body("internal_error", "Something went wrong."), status_code=500)
