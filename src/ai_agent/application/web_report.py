"""Deterministic report orchestration for the Web workspace."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import monotonic
from typing import Callable

from ..analysis_execution import SecurityAnalysisExecutor
from ..langchain.retrieval import RetrievedContext
from ..observability import elapsed_milliseconds, log_event
from ..research_planning import SecurityAnalysisRequest
from ..research_report import SecurityResearchReportBuilder
from ..tools import ToolRegistry
from .contracts import ResearchIntent
from .input_parser import ResearchIntentParser
from .narration import ReportNarrator
from .web_workspace_contracts import WebWorkspaceError


class WebReportService:
    """Interpret, execute, and optionally narrate one bounded research report."""

    _MAX_CONTENT_LENGTH = 4_000

    def __init__(
        self,
        *,
        tool_registry_factory: Callable[[], ToolRegistry],
        model_provider: str,
        intent_parser: ResearchIntentParser,
        retrieve: Callable[[str], RetrievedContext],
        narrator: ReportNarrator | None,
    ) -> None:
        self._tool_registry_factory = tool_registry_factory
        self._model_provider = model_provider
        self._intent_parser = intent_parser
        self._retrieve = retrieve
        self._narrator = narrator

    def run_report(
        self,
        *,
        content: str,
    ) -> dict[str, object]:
        """Interpret one natural-language request, then run safe research if ready."""

        started_at = monotonic()
        content = _content(content, max_length=self._MAX_CONTENT_LENGTH)
        log_event("web_report_started", input_characters=len(content), model_provider=self._model_provider)
        language_context = self._retrieve(content)
        intent = self._intent_parser.parse(content)
        if not intent.is_ready:
            payload = self._clarification_payload(intent, language_context)
            payload["analysis_duration_ms"] = elapsed_milliseconds(started_at)
            log_event(
                "web_report_completed",
                report_status="needs_clarification",
                duration_ms=payload["analysis_duration_ms"],
            )
            return payload
        if intent.symbol is None or intent.market is None:
            raise WebWorkspaceError("The request interpreter returned an incomplete research intent.")

        request = SecurityAnalysisRequest(
            symbol=intent.symbol,
            market=intent.market,
            scenario=intent.scenario,
            start_date=intent.start_date,
            end_date=intent.end_date,
        )
        try:
            analysis = SecurityAnalysisExecutor(self._tool_registry_factory()).execute(
                request,
                provider=_planning_provider(self._model_provider),
            )
        except (OSError, RuntimeError) as error:
            log_event(
                "deterministic_report_failed",
                level=logging.ERROR,
                error_type=type(error).__name__,
                duration_ms=elapsed_milliseconds(started_at),
            )
            raise WebWorkspaceError(
                "Configured market-data tools could not complete the request; check source configuration and try again."
            ) from error
        payload = SecurityResearchReportBuilder().build(analysis).to_dict()
        payload["request_status"] = "complete"
        payload["analysis_completed_at"] = _analysis_completed_at()
        payload["intent"] = intent.to_dict()
        payload["language_context"] = language_context.to_dict()
        self._add_optional_narrative(payload)
        payload["analysis_duration_ms"] = elapsed_milliseconds(started_at)
        log_event(
            "web_report_completed",
            report_status=str(payload["request_status"]),
            evidence_count=len(analysis.evidence),
            execution_error_count=len(analysis.execution_errors),
            duration_ms=payload["analysis_duration_ms"],
        )
        return payload

    def _clarification_payload(self, intent: ResearchIntent, language_context: RetrievedContext) -> dict[str, object]:
        return {
            "request_status": "needs_clarification",
            "analysis_completed_at": _analysis_completed_at(),
            "intent": intent.to_dict(),
            "clarifications": [item.to_dict() for item in intent.clarifications],
            "language_context": language_context.to_dict(),
            "message": "请补充以下信息后再次提交；系统不会猜测证券、市场或日期区间。",
        }

    def _add_optional_narrative(self, payload: dict[str, object]) -> None:
        if self._narrator is None:
            payload["narration_status"] = "not_configured"
            log_event("report_narration_skipped", reason="not_configured")
            return
        started_at = monotonic()
        try:
            payload["model_narrative"] = self._narrator.narrate(payload)
            payload["narration_status"] = "complete"
            payload["narration_provider"] = getattr(self._narrator, "provider_name", "configured_provider")
        except RuntimeError as error:
            payload["narration_status"] = "unavailable"
            log_event(
                "report_narration_failed",
                level=logging.WARNING,
                error_type=type(error).__name__,
                duration_ms=elapsed_milliseconds(started_at),
            )
            return
        log_event(
            "report_narration_completed",
            duration_ms=elapsed_milliseconds(started_at),
            provider=str(payload["narration_provider"]),
        )


def _content(value: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("content cannot be blank")
    if len(value) > max_length:
        raise ValueError(f"content must not exceed {max_length:,} characters")
    return value


def _planning_provider(provider: str) -> str:
    return provider if provider in {"codex", "qianfan", "bailian"} else "codex"


def _analysis_completed_at() -> str:
    return datetime.now(timezone.utc).isoformat()

