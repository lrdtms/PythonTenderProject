"""FastAPI entry point. Wires adapters; routers are added by each module owner."""

from fastapi import FastAPI
from sqlalchemy import create_engine, text

from app.config import get_settings

app = FastAPI(title="IntelTPS API", version="0.1.0")


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/health/db")
def health_db() -> dict[str, str]:
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
