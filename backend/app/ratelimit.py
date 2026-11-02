"""Small in-process sliding-window rate limiter (per client IP).

Limits brute force and abuse on public endpoints. State lives in this process only,
so with several instances each enforces its own budget; use an edge/WAF limit as well
if you scale out. Disabled when RATE_LIMIT_ENABLED=false (test suite).
"""

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, Request

from app.errors import ApiError

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _enabled() -> bool:
    return os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def reset() -> None:
    with _lock:
        _hits.clear()


def rate_limit(name: str, limit: int, window_seconds: int):
    """FastAPI dependency factory: at most `limit` calls per `window_seconds` per client IP."""

    def dependency(request: Request) -> None:
        if not _enabled():
            return
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with _lock:
            bucket = _hits[(name, ip)]
            while bucket and now - bucket[0] > window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                retry = max(1, int(window_seconds - (now - bucket[0])))
                raise ApiError(429, "RATE_LIMITED", "Too many requests. Try again shortly.", {"retry_after_seconds": retry})
            bucket.append(now)

    return Depends(dependency)
