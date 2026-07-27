"""Thread-safe development repository.

This implementation is intentionally process-local.  It gives the API and
application layer a complete persistence contract without pretending to be a
production multi-instance database.  A PostgreSQL implementation can replace
it without changing the application services.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Protocol
from uuid import uuid4

from ..application.contracts import (
    Conversation,
    ConversationMessage,
    ResearchReportRecord,
    ResearchTask,
    TaskStatus,
)


class ApplicationStore(Protocol):
    """Persistence operations with explicit user ownership on every read."""

    def create_conversation(self, user_id: str) -> Conversation: ...

    def get_conversation(self, user_id: str, conversation_id: str) -> Conversation | None: ...

    def add_message(self, user_id: str, conversation_id: str, role: str, content: str) -> ConversationMessage: ...

    def create_task(self, user_id: str, conversation_id: str, intent) -> ResearchTask: ...  # type: ignore[no-untyped-def]

    def get_task(self, user_id: str, task_id: str) -> ResearchTask | None: ...

    def update_task(self, task: ResearchTask) -> None: ...

    def create_report(self, user_id: str, task_id: str, payload: dict[str, object]) -> ResearchReportRecord: ...

    def get_report(self, user_id: str, report_id: str) -> ResearchReportRecord | None: ...


class InMemoryApplicationStore:
    """Safe for concurrent requests handled by one API process only."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._conversations: dict[str, Conversation] = {}
        self._messages: list[ConversationMessage] = []
        self._tasks: dict[str, ResearchTask] = {}
        self._reports: dict[str, ResearchReportRecord] = {}

    def create_conversation(self, user_id: str) -> Conversation:
        conversation = Conversation(id=_identifier("conv"), user_id=user_id, created_at=_now())
        with self._lock:
            self._conversations[conversation.id] = conversation
        return conversation

    def get_conversation(self, user_id: str, conversation_id: str) -> Conversation | None:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            return conversation if conversation and conversation.user_id == user_id else None

    def add_message(self, user_id: str, conversation_id: str, role: str, content: str) -> ConversationMessage:
        if role not in {"user", "assistant"}:
            raise ValueError("conversation messages must have user or assistant role")
        if self.get_conversation(user_id, conversation_id) is None:
            raise LookupError("conversation was not found for this user")
        message = ConversationMessage(
            id=_identifier("msg"),
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            content=content,
            created_at=_now(),
        )
        with self._lock:
            self._messages.append(message)
        return message

    def create_task(self, user_id: str, conversation_id: str, intent) -> ResearchTask:  # type: ignore[no-untyped-def]
        if self.get_conversation(user_id, conversation_id) is None:
            raise LookupError("conversation was not found for this user")
        now = _now()
        task = ResearchTask(
            id=_identifier("task"),
            user_id=user_id,
            conversation_id=conversation_id,
            intent=intent,
            status=TaskStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._tasks[task.id] = task
        return task

    def get_task(self, user_id: str, task_id: str) -> ResearchTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return task if task and task.user_id == user_id else None

    def update_task(self, task: ResearchTask) -> None:
        with self._lock:
            current = self._tasks.get(task.id)
            if current is None or current.user_id != task.user_id:
                raise LookupError("task was not found for this user")
            self._tasks[task.id] = task

    def create_report(self, user_id: str, task_id: str, payload: dict[str, object]) -> ResearchReportRecord:
        if self.get_task(user_id, task_id) is None:
            raise LookupError("task was not found for this user")
        report = ResearchReportRecord(
            id=_identifier("report"),
            user_id=user_id,
            task_id=task_id,
            payload=payload,
            created_at=_now(),
        )
        with self._lock:
            self._reports[report.id] = report
        return report

    def get_report(self, user_id: str, report_id: str) -> ResearchReportRecord | None:
        with self._lock:
            report = self._reports.get(report_id)
            return report if report and report.user_id == user_id else None


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _now() -> datetime:
    return datetime.now(timezone.utc)
