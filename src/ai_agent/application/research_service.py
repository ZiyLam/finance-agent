"""Use cases for conversation submission and deterministic research execution."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from ..analysis_execution import SecurityAnalysisExecutor
from ..research_planning import SecurityAnalysisRequest
from ..research_report import SecurityResearchReportBuilder
from ..tools import ToolRegistry
from ..infrastructure.store import ApplicationStore
from ..infrastructure.task_queue import TaskQueue
from .contracts import ResearchTask, Submission, SubmissionStatus, TaskStatus
from .input_parser import ResearchIntentParser
from .narration import ReportNarrator


class ResearchService:
    """Owns user-scoped conversation submission and queued research work."""

    def __init__(
        self,
        *,
        store: ApplicationStore,
        queue: TaskQueue,
        parser: ResearchIntentParser,
        tool_registry_factory: Callable[[], ToolRegistry],
        narrator: ReportNarrator | None = None,
    ) -> None:
        self._store = store
        self._queue = queue
        self._parser = parser
        self._tool_registry_factory = tool_registry_factory
        self._narrator = narrator

    def create_conversation(self, user_id: str):  # type: ignore[no-untyped-def]
        return self._store.create_conversation(user_id)

    def submit_message(self, user_id: str, conversation_id: str, content: str) -> Submission:
        if self._store.get_conversation(user_id, conversation_id) is None:
            raise LookupError("conversation was not found for this user")
        intent = self._parser.parse(content)
        self._store.add_message(user_id, conversation_id, "user", content)
        if not intent.is_ready:
            message = "请先补充或确认以下信息：" + "；".join(
                item.question for item in intent.clarifications
            )
            self._store.add_message(user_id, conversation_id, "assistant", message)
            return Submission(
                status=SubmissionStatus.NEEDS_CLARIFICATION,
                intent=intent,
                assistant_message=message,
            )

        task = self._store.create_task(user_id, conversation_id, intent)
        self._queue.enqueue(task)
        message = "研究任务已创建。完成后将提供数据范围、来源、风险提示和报告。"
        self._store.add_message(user_id, conversation_id, "assistant", message)
        return Submission(
            status=SubmissionStatus.QUEUED,
            intent=intent,
            task_id=task.id,
            assistant_message=message,
        )

    def get_task(self, user_id: str, task_id: str) -> ResearchTask | None:
        return self._store.get_task(user_id, task_id)

    def get_report(self, user_id: str, report_id: str):  # type: ignore[no-untyped-def]
        return self._store.get_report(user_id, report_id)

    def run_next_task(self) -> ResearchTask | None:
        """Execute one queued item. Production workers call this use case independently."""

        queued = self._queue.dequeue()
        if queued is None:
            return None
        task = self._store.get_task(queued.user_id, queued.id)
        if task is None or task.status is not TaskStatus.QUEUED:
            return task

        running = replace(task, status=TaskStatus.RUNNING, updated_at=_now())
        self._store.update_task(running)
        try:
            request = SecurityAnalysisRequest(
                symbol=_required(running.intent.symbol, "symbol"),
                market=_required(running.intent.market, "market"),
                scenario=running.intent.scenario,
                start_date=running.intent.start_date,
                end_date=running.intent.end_date,
            )
            result = SecurityAnalysisExecutor(self._tool_registry_factory()).execute(request)
            report = SecurityResearchReportBuilder().build(result)
            payload = report.to_dict()
            self._add_optional_narrative(payload)
            record = self._store.create_report(running.user_id, running.id, payload)
            completed = replace(
                running,
                status=TaskStatus.COMPLETED,
                report_id=record.id,
                updated_at=_now(),
            )
            self._store.update_task(completed)
            return completed
        except (RuntimeError, ValueError, OSError) as error:
            # Provider internals and credentials never belong in a user-visible task error.
            del error
            failed = replace(
                running,
                status=TaskStatus.FAILED,
                safe_error="研究任务暂时无法完成；请检查数据源配置后重试。",
                updated_at=_now(),
            )
            self._store.update_task(failed)
            return failed

    def _add_optional_narrative(self, payload: dict[str, object]) -> None:
        if self._narrator is None:
            payload["narration_status"] = "not_configured"
            return
        try:
            payload["model_narrative"] = self._narrator.narrate(payload)
            payload["narration_status"] = "complete"
            provider_name = getattr(self._narrator, "provider_name", "configured_provider")
            payload["narration_provider"] = provider_name
        except RuntimeError:
            # A report with deterministic evidence remains useful if the model
            # is unavailable, rate-limited, or returns malformed output.
            payload["narration_status"] = "unavailable"


def _required(value, name: str):  # type: ignore[no-untyped-def]
    if value is None:
        raise ValueError(f"{name} is required before a task can run")
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)
