"""Stable Web workspace contracts shared by focused application services."""

from __future__ import annotations

from dataclasses import dataclass


class WebWorkspaceError(RuntimeError):
    """A safe Web-facing error that never includes provider internals."""


@dataclass(frozen=True, slots=True)
class WebAgentReply:
    """One Agent or deterministic research response returned to the browser."""

    conversation_id: str
    text: str
    tool_calls: tuple[dict[str, object], ...]
    language_context: dict[str, object]
    analysis_completed_at: str = ""
    analysis_duration_ms: int = 0
    response_kind: str = "agent"
    research_period: dict[str, object] | None = None
    entity_candidates: tuple[dict[str, str], ...] = ()
    snapshot: dict[str, object] | None = None
    snapshots: tuple[dict[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "conversation_id": self.conversation_id,
            "text": self.text,
            "tool_calls": list(self.tool_calls),
            "language_context": self.language_context,
            "analysis_completed_at": self.analysis_completed_at,
            "analysis_duration_ms": self.analysis_duration_ms,
            "response_kind": self.response_kind,
            "research_period": self.research_period,
            "entity_candidates": list(self.entity_candidates),
            "snapshot": self.snapshot,
            "snapshots": list(self.snapshots),
        }

