"""FastAPI entry point. Wires routers, error handling and the CSRF check."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.errors import error_body, register_error_handlers
from app.api.routers import auth, documents, jobs, members, tenders
from app.db.session import ping
from app.infrastructure.model_registry import import_all_models

import_all_models()

app = FastAPI(title="IntelTPS API", version="0.1.0")
register_error_handlers(app)

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "IntelTPS"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def require_csrf_header(request: Request, call_next):
    """State-changing API requests must carry a custom header. Cross-site forms cannot set it,
    and SameSite=Lax cookies add a second layer (ADR-0008, ADR-0010)."""
    if (
        request.method in UNSAFE_METHODS
        and request.url.path.startswith("/api/")
        and request.headers.get(CSRF_HEADER) != CSRF_VALUE
    ):
        return JSONResponse(
            error_body("csrf_failed", "Missing or invalid request header."), status_code=403
        )
    return await call_next(request)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/health/db")
def health_db() -> dict[str, str]:
    ping()
    return {"status": "ok", "database": "reachable"}


app.include_router(auth.router)
app.include_router(members.router)
app.include_router(tenders.router)
app.include_router(documents.router)
app.include_router(jobs.router)
