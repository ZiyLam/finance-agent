"""Local development limiter with user and provider dimensions.

The interface is deliberately compatible with a future Redis-backed token
bucket.  Never use this in-memory implementation across multiple API workers.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import RLock
from time import monotonic


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: float = 0.0


class InMemoryRateLimiter:
    """Atomic sliding-window limiter for one service process."""

    def __init__(self, *, clock=monotonic) -> None:  # type: ignore[no-untyped-def]
        self._clock = clock
        self._lock = RLock()
        self._events: dict[str, deque[float]] = {}

    def acquire(self, key: str, *, limit: int, window_seconds: float) -> RateLimitDecision:
        if not key.strip() or limit < 1 or window_seconds <= 0:
            raise ValueError("rate-limit key, limit, and window_seconds must be valid")
        now = self._clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= window_seconds:
                events.popleft()
            if len(events) >= limit:
                return RateLimitDecision(False, max(0.0, window_seconds - (now - events[0])))
            events.append(now)
        return RateLimitDecision(True)
