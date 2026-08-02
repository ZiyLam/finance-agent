"""Application service for the authenticated personal Web workspace."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from queue import Empty, Queue
from threading import RLock, Thread
from time import monotonic
from typing import Callable

from ..agent import Agent
from ..langchain.retrieval import FinanceLanguageChain, RetrievedContext
from ..observability import elapsed_milliseconds, log_event
from ..tools import ToolRegistry
from .beginner_research import BeginnerResearchService
from .contracts import ResearchIntent
from .entity_resolution import EntityResolution, SecurityEntityResolver
from .index_research import IndexResearchService, IndexResolver, professional_research_catalog
from .input_parser import ResearchIntentParser
from .narration import ReportNarrator
from .professional_research import ProfessionalResearchService
from .security_discovery import SecurityDiscoveryService
from .web_report import WebReportService
from .web_workspace_contracts import WebAgentReply, WebWorkspaceError


@dataclass(slots=True)
class _WebAgentSession:
    """One short-lived conversation Agent and its per-conversation lock."""

    agent: Agent
    last_access: float
    active_requests: int = 0
    lock: RLock = field(default_factory=RLock, repr=False)


class WebWorkspaceService:
    """Run personal Web requests through the same LangChain and tool boundaries.

    Each browser conversation gets its own bounded LangChain Agent instance.
    Market-data research uses the existing deterministic plan/executor/report
    sequence, with optional model narration layered only over safe report fields.
    """

    _MAX_CONTENT_LENGTH = 4_000
    _INDEX_MARKET_DATA_TIMEOUT_SECONDS = 3.0

    def __init__(
        self,
        *,
        tool_registry_factory: Callable[[], ToolRegistry],
        agent_factory: Callable[[], Agent],
        model_provider: str,
        narrator: ReportNarrator | None = None,
        intent_parser: ResearchIntentParser | None = None,
        language_chain: FinanceLanguageChain | None = None,
        entity_resolver: SecurityEntityResolver | None = None,
        beginner_research: BeginnerResearchService | None = None,
        index_resolver: IndexResolver | None = None,
        index_research: IndexResearchService | None = None,
        security_discovery: SecurityDiscoveryService | None = None,
        market_scan_timeout_seconds: float = 5.0,
        session_ttl_seconds: float = 1_800.0,
        max_conversations: int = 50,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        if max_conversations < 1:
            raise ValueError("max_conversations must be at least 1")
        if market_scan_timeout_seconds <= 0:
            raise ValueError("market_scan_timeout_seconds must be positive")
        self._tool_registry_factory = tool_registry_factory
        self._agent_factory = agent_factory
        self._model_provider = model_provider
        self._narrator = narrator
        self._intent_parser = intent_parser or ResearchIntentParser()
        self._language_chain = language_chain or FinanceLanguageChain()
        self._entity_resolver = entity_resolver or SecurityEntityResolver()
        self._beginner_research = beginner_research or BeginnerResearchService(
            tool_registry_factory=tool_registry_factory
        )
        self._index_resolver = index_resolver or IndexResolver()
        self._index_research = index_research or IndexResearchService(
            BeginnerResearchService(
                tool_registry_factory=tool_registry_factory,
                timeout_seconds=self._INDEX_MARKET_DATA_TIMEOUT_SECONDS,
            )
        )
        self._security_discovery = security_discovery or SecurityDiscoveryService(tool_registry_factory)
        self._professional_service = ProfessionalResearchService(
            self._index_research,
            self._retrieve,
        )
        self._report_service = WebReportService(
            tool_registry_factory=tool_registry_factory,
            model_provider=model_provider,
            intent_parser=self._intent_parser,
            retrieve=self._retrieve,
            narrator=narrator,
        )
        self._market_scan_timeout_seconds = market_scan_timeout_seconds
        self._session_ttl_seconds = session_ttl_seconds
        self._max_conversations = max_conversations
        self._clock = clock
        self._agents: dict[str, _WebAgentSession] = {}
        self._agent_lock = RLock()

    def status(self) -> dict[str, object]:
        """Return capability metadata without ever returning credentials."""

        try:
            tools = self._tool_registry_factory().definitions()
        except RuntimeError as error:
            log_event(
                "web_status_tool_initialization_failed",
                level=logging.ERROR,
                error_type=type(error).__name__,
            )
            raise WebWorkspaceError("Configured market-data tools could not be initialized.") from error
        return {
            "entry": "personal_web_workspace",
            "agent_framework": "langchain",
            "model_provider": self._model_provider,
            "narration_configured": self._narrator is not None,
            "configured_tools": [tool.name for tool in tools],
            "tool_policy": "read_only_research",
            "language_enhancement": "lcel_rag",
            "professional_research": professional_research_catalog(),
            "conversation_session_policy": {
                "idle_ttl_seconds": self._session_ttl_seconds,
                "max_cached_conversations": self._max_conversations,
            },
        }

    def professional_research(
        self,
        *,
        conversation_id: str,
        content: str,
        start_date: date,
        end_date: date,
        markets: tuple[str, ...],
        indices: tuple[str, ...],
        metrics: tuple[str, ...],
    ) -> WebAgentReply:
        """Delegate explicit multi-index inputs to the focused professional service."""

        return self._professional_service.run(
            conversation_id=conversation_id,
            content=content,
            start_date=start_date,
            end_date=end_date,
            markets=markets,
            indices=indices,
            metrics=metrics,
        )

    def chat(self, *, conversation_id: str, content: str) -> WebAgentReply:
        """Invoke the LangChain Agent and retain its memory by conversation ID."""

        started_at = monotonic()
        normalized_id = _conversation_id(conversation_id)
        content = _content(content, max_length=self._MAX_CONTENT_LENGTH)
        research_intent = self._intent_parser.parse(content)
        log_event(
            "web_chat_started",
            model_provider=self._model_provider,
            input_characters=len(content),
        )
        language_context = self._retrieve(content)
        if language_context.intent.name == "market_scan":
            market_scan_started_at = monotonic()
            log_event("market_scan_started")
            reply = _with_analysis_duration(
                self._market_scan_reply(
                    normalized_id,
                    language_context,
                    research_intent,
                ),
                started_at,
            )
            market_data = reply.snapshot if isinstance(reply.snapshot, dict) else {}
            log_event(
                "market_scan_completed",
                market_data_status=market_data.get("status", "unavailable"),
                duration_ms=elapsed_milliseconds(market_scan_started_at),
            )
            return _complete_web_chat(reply)
        index = self._index_resolver.resolve(content)
        if index is not None:
            index_started_at = monotonic()
            log_event("index_research_started", index_key=index.key)
            snapshot = self._index_research.overview(index)
            reply = _with_analysis_duration(
                self._index_snapshot_reply(normalized_id, language_context, snapshot),
                started_at,
            )
            log_event(
                "index_research_completed",
                index_key=index.key,
                duration_ms=elapsed_milliseconds(index_started_at),
            )
            return _complete_web_chat(reply)
        resolution = self._entity_resolver.resolve(content)
        log_event(
            "entity_resolution_completed",
            candidate_count=len(resolution.candidates),
            resolution_kind=(
                "ambiguous" if resolution.is_ambiguous else "unique" if resolution.is_unique else "unresolved"
            ),
        )
        if not resolution.candidates and _uses_default_beginner_snapshot(content):
            resolution = self._security_discovery.discover(content)
            log_event(
                "security_discovery_completed",
                candidate_count=len(resolution.candidates),
            )
        if resolution.is_ambiguous:
            reply = _with_analysis_duration(
                self._candidate_snapshots_reply(normalized_id, language_context, resolution),
                started_at,
            )
            return _complete_web_chat(reply)
        if resolution.is_unique and _uses_default_beginner_snapshot(content):
            snapshot = self._beginner_research.latest_week(resolution.candidates[0]).to_dict()
            reply = _with_analysis_duration(
                self._beginner_snapshot_reply(normalized_id, language_context, snapshot),
                started_at,
            )
            return _complete_web_chat(reply)
        session: _WebAgentSession | None = None
        agent_started_at = monotonic()
        try:
            session = self._lease_agent(normalized_id)
            log_event("agent_invocation_started", max_tool_rounds=2)
            # Memory belongs to one conversation, so requests for that same
            # conversation remain ordered. Other conversations can invoke their
            # own Agent without waiting for a model call under a global lock.
            with session.lock:
                result = session.agent.run(
                    content,
                    retrieved_context=_agent_retrieval_context(language_context, research_intent),
                )
        except (OSError, RuntimeError) as error:
            log_event(
                "agent_invocation_failed",
                level=logging.ERROR,
                error_type=type(error).__name__,
                duration_ms=elapsed_milliseconds(agent_started_at),
            )
            raise WebWorkspaceError(
                "The configured model or a local research tool is temporarily unavailable; check the local setup and try again."
            ) from error
        finally:
            if session is not None:
                self._release_agent(session)
        tool_names = tuple(call.name for call in result.tool_calls)
        log_event(
            "agent_invocation_completed",
            duration_ms=elapsed_milliseconds(agent_started_at),
            tool_call_count=len(tool_names),
            tool_names=tool_names,
        )
        reply = WebAgentReply(
            conversation_id=normalized_id,
            text=result.text,
            tool_calls=tuple(
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in result.tool_calls
            ),
            language_context=language_context.to_dict(),
            analysis_completed_at=_analysis_completed_at(),
            analysis_duration_ms=elapsed_milliseconds(started_at),
            research_period=_research_period(research_intent),
        )
        return _complete_web_chat(reply)

    def _lease_agent(self, conversation_id: str) -> _WebAgentSession:
        """Return one session while enforcing idle expiry and an LRU capacity."""

        now = self._clock()
        with self._agent_lock:
            self._discard_expired_agents(now)
            session = self._agents.get(conversation_id)
            if session is None:
                self._evict_idle_agents_until_within_capacity()
                if len(self._agents) >= self._max_conversations:
                    raise WebWorkspaceError(
                        "The Web workspace has reached its active conversation limit; try again shortly."
                    )
                session = _WebAgentSession(agent=self._agent_factory(), last_access=now)
                self._agents[conversation_id] = session
            session.active_requests += 1
            session.last_access = now
            return session

    def _release_agent(self, session: _WebAgentSession) -> None:
        with self._agent_lock:
            session.active_requests = max(0, session.active_requests - 1)
            session.last_access = self._clock()

    def _discard_expired_agents(self, now: float) -> None:
        expired_ids = [
            conversation_id
            for conversation_id, session in self._agents.items()
            if session.active_requests == 0 and now - session.last_access >= self._session_ttl_seconds
        ]
        for conversation_id in expired_ids:
            del self._agents[conversation_id]

    def _evict_idle_agents_until_within_capacity(self) -> None:
        while len(self._agents) >= self._max_conversations:
            idle_agents = [
                (conversation_id, session)
                for conversation_id, session in self._agents.items()
                if session.active_requests == 0
            ]
            if not idle_agents:
                return
            least_recently_used_id, _ = min(idle_agents, key=lambda item: item[1].last_access)
            del self._agents[least_recently_used_id]

    def _candidate_snapshots_reply(
        self,
        conversation_id: str,
        language_context: RetrievedContext,
        resolution: EntityResolution,
    ) -> WebAgentReply:
        snapshots = tuple(self._beginner_research.latest_week(candidate).to_dict() for candidate in resolution.candidates)
        return WebAgentReply(
            conversation_id=conversation_id,
            text=(
                "已识别到多个可能的上市证券。为避免让你自行决定，下面会并列展示每个候选的基础概览；"
                "请留意不同市场、币种和证券类型的差异。"
            ),
            tool_calls=(),
            language_context=language_context.to_dict(),
            analysis_completed_at=_analysis_completed_at(),
            response_kind="candidate_snapshots",
            snapshots=snapshots,
        )

    def _market_scan_reply(
        self,
        conversation_id: str,
        language_context: RetrievedContext,
        research_intent: ResearchIntent,
    ) -> WebAgentReply:
        """Read the bounded sector ranking once without invoking the model."""

        tool_name = "eastmoney_market_scan"
        snapshot: dict[str, object] = {
            "status": "unavailable",
            "source": "Eastmoney A-share industry ranking",
            "freshness": "current_or_delayed",
            "market_sentiment": {
                "label": "待数据",
                "tone": "flat",
            },
            "leading_industries": [],
            "lagging_industries": [],
            "reason": "板块排行远端数据源当前不可用，请稍后在参数配置页复测连通性。",
        }
        try:
            registry = self._tool_registry_factory()
            if tool_name in {tool.name for tool in registry.definitions()}:
                raw = self._execute_market_scan(registry, tool_name)
                if raw is not None and not raw.startswith("ERROR:"):
                    payload = json.loads(raw)
                    if (
                        isinstance(payload, dict)
                        and isinstance(payload.get("leading_industries"), list)
                        and isinstance(payload.get("lagging_industries"), list)
                        and isinstance(payload.get("market_sentiment"), dict)
                    ):
                        snapshot = {**payload, "status": "complete"}
        except (OSError, RuntimeError, TypeError, json.JSONDecodeError):
            # Keep provider internals out of the result; the tool and HTTP logs
            # already retain payload-free event type and duration metadata.
            pass

        is_complete = snapshot.get("status") == "complete"
        text = (
            "已直接读取近期 A 股行业涨跌样本，并保留涨跌幅、市场情绪、数据时效和风险边界；"
            "本路径不需要二次模型调用。"
            if is_complete
            else "板块排行远端数据源当前不可用；系统已在一次受控读取后停止，未继续等待第二轮模型。"
        )
        return WebAgentReply(
            conversation_id=conversation_id,
            text=text,
            tool_calls=(
                {
                    "id": "deterministic-market-scan",
                    "name": tool_name,
                    "arguments": {"limit": 8},
                },
            ),
            language_context=language_context.to_dict(),
            analysis_completed_at=_analysis_completed_at(),
            response_kind="market_scan",
            research_period=_research_period(research_intent),
            snapshot=snapshot,
        )

    def _execute_market_scan(self, registry: ToolRegistry, tool_name: str) -> str | None:
        """Return promptly when the single remote sector read stalls."""

        result: Queue[str] = Queue(maxsize=1)

        def execute() -> None:
            result.put(registry.execute(tool_name, {"limit": 8}))

        thread = Thread(target=execute, daemon=True, name="market-scan-read")
        thread.start()
        try:
            return result.get(timeout=self._market_scan_timeout_seconds)
        except Empty:
            return None

    @staticmethod
    def _index_snapshot_reply(
        conversation_id: str,
        language_context: RetrievedContext,
        snapshot: dict[str, object],
    ) -> WebAgentReply:
        index = snapshot.get("index")
        market_data = snapshot.get("market_data")
        name = index.get("display_name") if isinstance(index, dict) else "该指数"
        if isinstance(market_data, dict) and market_data.get("status") == "complete":
            text = (
                f"已为{name}完成单次全景研究：包含近期行情、最近五个交易日表现、"
                "风格与估值边界、成分行业边界及风险提示；未连接的数据不会推断。"
            )
        else:
            text = (
                f"已为{name}生成风格、行业与风险边界；近期行情暂不可用，"
                "原因见结果说明，未使用模型或重复数据请求补写。"
            )
        return WebAgentReply(
            conversation_id=conversation_id,
            text=text,
            tool_calls=(),
            language_context=language_context.to_dict(),
            analysis_completed_at=_analysis_completed_at(),
            response_kind="index_snapshot",
            snapshot=snapshot,
        )

    @staticmethod
    def _beginner_snapshot_reply(
        conversation_id: str,
        language_context: RetrievedContext,
        snapshot: dict[str, object],
    ) -> WebAgentReply:
        security = snapshot.get("security")
        market_data = snapshot.get("market_data")
        name = security.get("display_name") if isinstance(security, dict) else "该证券"
        if isinstance(market_data, dict) and market_data.get("status") == "complete":
            text = (
                f"已为{name}生成基础概览：默认范围为最新可用日线和最近五个交易日。"
                "价格数据会明确标注其时效；财报数据未接入时不会补写或推断。"
            )
        else:
            text = (
                f"已识别为{name}，并按默认范围尝试读取最新可用日线和最近五个交易日；"
                "本次行情数据暂不可用，具体原因见结果说明。"
            )
        return WebAgentReply(
            conversation_id=conversation_id,
            text=text,
            tool_calls=(),
            language_context=language_context.to_dict(),
            analysis_completed_at=_analysis_completed_at(),
            response_kind="beginner_snapshot",
            snapshot=snapshot,
        )

    def run_report(self, *, content: str) -> dict[str, object]:
        """Delegate deterministic report execution to its focused application service."""

        return self._report_service.run_report(content=content)

    def _retrieve(self, content: str) -> RetrievedContext:
        started_at = monotonic()
        log_event("rag_retrieval_started", input_characters=len(content))
        try:
            context = self._language_chain.invoke(content)
        except (RuntimeError, ValueError) as error:
            log_event(
                "rag_retrieval_failed",
                level=logging.ERROR,
                error_type=type(error).__name__,
                duration_ms=elapsed_milliseconds(started_at),
            )
            raise WebWorkspaceError("The local language enhancement chain is unavailable.") from error
        log_event(
            "rag_retrieval_completed",
            intent_name=context.intent.name,
            document_count=len(context.documents),
            duration_ms=elapsed_milliseconds(started_at),
        )
        return context

def _conversation_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 80 or not normalized.replace("-", "").replace("_", "").isalnum():
        raise ValueError("conversation_id must contain only letters, numbers, hyphens, and underscores")
    return normalized


def _content(value: str, *, max_length: int) -> str:
    """Keep every Web path within the same bounded input contract as the API."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("content cannot be blank")
    if len(value) > max_length:
        raise ValueError(f"content must not exceed {max_length:,} characters")
    return value


def _complete_web_chat(reply: WebAgentReply) -> WebAgentReply:
    """Record the common terminal event for every successful chat path."""

    log_event(
        "web_chat_completed",
        response_kind=reply.response_kind,
        duration_ms=reply.analysis_duration_ms,
    )
    return reply


def _with_analysis_duration(reply: WebAgentReply, started_at: float) -> WebAgentReply:
    """Freeze the end-to-end request duration at the same point used for logging."""

    return replace(reply, analysis_duration_ms=elapsed_milliseconds(started_at))


def _agent_retrieval_context(language_context: RetrievedContext, intent: ResearchIntent) -> str:
    """Add an auditable resolved date window without changing the user's message."""

    context = language_context.prompt_block()
    period = _research_period(intent)
    if period is None:
        return context
    return (
        f"{context}\n\n"
        "Resolved research date window: "
        f"start_date={period['start_date']}; end_date={period['end_date']}. "
        "Use this window for any historical-data tool call."
    )


def _research_period(intent: ResearchIntent) -> dict[str, object] | None:
    """Expose only normalized date metadata that is safe for the Web client."""

    if intent.start_date is None or intent.end_date is None:
        return None
    return {
        "start_date": intent.start_date,
        "end_date": intent.end_date,
        "assumptions": list(intent.assumptions),
    }


def _analysis_completed_at() -> str:
    """Use a timezone-aware server timestamp for a completed user-visible result."""

    return datetime.now(timezone.utc).isoformat()


def _uses_default_beginner_snapshot(content: str) -> bool:
    """Keep an explicit period or a complex question on the normal Agent path.

    A bare selected ticker/name is a common concise request.  It benefits from a
    fixed one-request snapshot much more than from asking a model to infer a
    market, date range, and tool sequence.  Requests that already contain a
    time window or ask for a comparison/forecast retain the open Agent entry.
    """

    normalized = content.casefold()
    has_research_goal = any(
        phrase in normalized
        for phrase in ("分析", "研究", "走势", "历史", "报告", "研报", "analysis", "research", "trend")
    )
    has_complex_goal = has_research_goal or any(
        phrase in normalized
        for phrase in (
            "比较",
            "对比",
            "预测",
            "风险",
            "估值",
            "深度",
            "详细",
            "为什么",
            "怎么",
            "建议",
            "板块",
            "行业",
            "市场",
            "热点",
            "关注",
        )
    )
    is_point_in_time_quote = any(
        phrase in normalized
        for phrase in (
            "最新价格",
            "最新价",
            "实时价格",
            "实时行情",
            "当前价格",
            "当前价",
            "现价",
            "最新报价",
            "实时报价",
            "latest price",
            "current price",
            "latest quote",
            "realtime quote",
            "real-time quote",
        )
    )
    if is_point_in_time_quote and not has_complex_goal:
        return True

    has_explicit_time_term = any(
        phrase in normalized
        for phrase in (
            "近期",
            "最近",
            "近来",
            "本周",
            "上周",
            "本月",
            "上月",
            "今年",
            "去年",
            "短期",
            "中期",
            "长期",
            "实时",
            "最新",
            "today",
            "yesterday",
            "recent",
        )
    )
    has_time_window = has_explicit_time_term or bool(
        re.search(r"\d{4}\s*[-/.年]", normalized)
        or re.search(r"近\s*(?:期|\d+)|最近|过去|本周|上周|本月|上月|今年|去年|季度|财年", normalized)
    )
    return not has_time_window and not has_complex_goal
