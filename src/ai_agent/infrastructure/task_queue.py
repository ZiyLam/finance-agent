"""Task-queue contract and in-process development implementation."""

from __future__ import annotations

from collections import deque
from threading import RLock
from typing import Protocol

from ..application.contracts import ResearchTask


class TaskQueue(Protocol):
    def enqueue(self, task: ResearchTask) -> None: ...

    def dequeue(self) -> ResearchTask | None: ...


class InMemoryTaskQueue:
    """FIFO queue for local development and tests, not a distributed queue."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._tasks: deque[ResearchTask] = deque()

    def enqueue(self, task: ResearchTask) -> None:
        with self._lock:
            self._tasks.append(task)

    def dequeue(self) -> ResearchTask | None:
        with self._lock:
            return self._tasks.popleft() if self._tasks else None
