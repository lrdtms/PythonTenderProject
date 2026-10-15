"""A small in-memory sliding-window rate limiter (single process; enough for this deployment)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.config import get_settings
from app.kernel import RateLimited


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: float) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] > window_seconds:
                events.popleft()
            if len(events) >= limit:
                raise RateLimited("Too many attempts. Try again later.")
            events.append(now)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    """The configured proxy header when set (CF-Connecting-IP behind the tunnel), otherwise the
    socket peer. X-Forwarded-For is never trusted: any client can send it."""
    header = get_settings().client_ip_header
    if header:
        value = request.headers.get(header, "").strip()
        if value:
            return value
    return request.client.host if request.client else "unknown"
