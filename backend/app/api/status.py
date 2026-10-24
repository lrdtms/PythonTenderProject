"""Public status for the /status page and the start-demo script. Parts are reported as words
only: no version, host, path or model name ever appears in the answer."""

from __future__ import annotations

import time
import urllib.request

from app.config import get_settings
from app.db.session import ping

MODEL_TIMEOUT_S = 2.0
MODEL_CACHE_S = 10.0

_model_cache: tuple[float, str] | None = None


def reset_cache() -> None:
    global _model_cache
    _model_cache = None


def _fetch_tags(url: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 (configured http URL)
            return response.status == 200
    except Exception:
        return False


def _model() -> str:
    global _model_cache
    settings = get_settings()
    if settings.llm_provider == "fake":
        return "not_configured"
    now = time.monotonic()
    if _model_cache and now - _model_cache[0] < MODEL_CACHE_S:
        return _model_cache[1]
    up = _fetch_tags(settings.llm_base_url.rstrip("/") + "/api/tags", MODEL_TIMEOUT_S)
    _model_cache = (now, "ok" if up else "down")
    return _model_cache[1]


def get_status() -> dict[str, str]:
    try:
        ping()
        database = "ok"
    except Exception:
        database = "down"
    return {"api": "ok", "database": database, "model": _model()}
