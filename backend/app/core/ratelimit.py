"""Small in-process rate limiter for sign-in endpoints (per IP address).

Per-phone and per-account limits live in the database (see AuthService); this
adds a per-IP ceiling so one client can't spray codes at many numbers. With
several API processes, put a shared limiter (e.g. at the load balancer) in front.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.core.errors import RateLimited


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, bucket: str, key: str, *, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        hits = self._hits[(bucket, key)]
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            raise RateLimited("Too many attempts. Please wait a few minutes and try again.")
        hits.append(now)
        if len(self._hits) > 50_000:  # keep memory bounded
            self._hits.clear()

    def reset(self) -> None:
        self._hits.clear()
