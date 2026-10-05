"""Small in-memory sliding-window limiter (per process, per user). Fine for one API instance."""
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry = int(self.window - (now - hits[0])) + 1
            raise HTTPException(status_code=429, detail="Too many requests; slow down.",
                                headers={"Retry-After": str(retry)})
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()
