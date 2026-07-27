"""Stable application contracts shared by the API, workers, and mini-program."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ..analysis_tags import AnalysisScenario, Market


class SubmissionStatus(StrEnum):
    """The user-visible state after a research message is submitted."""

    NEEDS_CLARIFICATION = "needs_clarification"
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(StrEnum):
    """Durable lifecycle states for a background research task."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Clarification:
    """One item the user must confirm before data collection may start."""

    field: str
    question: str
    options: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"field": self.field, "question": self.question, "options": list(self.options)}


@dataclass(frozen=True, slots=True)
class ResearchIntent:
    """Normalized interpretation of one natural-language research request."""

    original_text: str
    scenario: AnalysisScenario
    market: Market | None
    symbol: str | None
    start_date: str | None = None
    end_date: str | None = None
    assumptions: tuple[str, ...] = ()
    clarifications: tuple[Clarification, ...] = ()

    @property
    def is_ready(self) -> bool:
        return not self.clarifications

    def to_dict(self) -> dict[str, object]:
        return {
            "original_text": self.original_text,
            "scenario": self.scenario.value,
            "market": self.market.value if self.market else None,
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "assumptions": list(self.assumptions),
            "clarifications": [item.to_dict() for item in self.clarifications],
        }


@dataclass(frozen=True, slots=True)
class Conversation:
    """A conversation owned by exactly one authenticated user."""

    id: str
    user_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """One persisted user or assistant message, never shared across users."""

    id: str
    conversation_id: str
    user_id: str
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ResearchTask:
    """A queued deterministic research execution."""

    id: str
    user_id: str
    conversation_id: str
    intent: ResearchIntent
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    report_id: str | None = None
    safe_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "report_id": self.report_id,
            "safe_error": self.safe_error,
            "intent": self.intent.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ResearchReportRecord:
    """A report document owned by the task's user."""

    id: str
    user_id: str
    task_id: str
    payload: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Submission:
    """Result of submitting a chat message to the research application."""

    status: SubmissionStatus
    intent: ResearchIntent
    task_id: str | None = None
    assistant_message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "intent": self.intent.to_dict(),
            "task_id": self.task_id,
            "assistant_message": self.assistant_message,
        }
