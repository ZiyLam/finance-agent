"""Small thread-safe TTL cache used only for local development."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Generic, TypeVar

Value = TypeVar("Value")


@dataclass(frozen=True, slots=True)
class _CacheEntry(Generic[Value]):
    value: Value
    expires_at: float


class InMemoryTtlCache(Generic[Value]):
    """A replaceable cache; use Redis for any multi-process deployment."""

    def __init__(self, *, clock=monotonic) -> None:  # type: ignore[no-untyped-def]
        self._clock = clock
        self._lock = RLock()
        self._entries: dict[str, _CacheEntry[Value]] = {}

    def get(self, key: str) -> Value | None:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._entries[key]
                return None
            return entry.value

    def set(self, key: str, value: Value, *, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        with self._lock:
            self._entries[key] = _CacheEntry(value=value, expires_at=self._clock() + ttl_seconds)
