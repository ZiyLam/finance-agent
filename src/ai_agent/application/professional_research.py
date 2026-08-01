"""Deterministic professional multi-index research orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import date, datetime, timezone
from time import monotonic
from typing import Callable

from ..langchain.retrieval import RetrievedContext
from ..observability import elapsed_milliseconds, log_event
from .index_research import (
    PROFESSIONAL_MARKETS,
    PROFESSIONAL_METRIC_KEYS,
    IndexResearchService,
    get_index,
)
from .web_workspace_contracts import WebAgentReply


class ProfessionalResearchService:
    """Validate explicit inputs and compare reviewed indices without an LLM."""

    def __init__(
        self,
        index_research: IndexResearchService,
        retrieve: Callable[[str], RetrievedContext],
    ) -> None:
        self._index_research = index_research
        self._retrieve = retrieve

    def run(
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
        """Run a bounded multi-index comparison from explicit professional inputs."""

        started_at = monotonic()
        normalized_id = _conversation_id(conversation_id)
        notes = content.strip() if isinstance(content, str) else ""
        if len(notes) > 2_000:
            raise ValueError("professional content must not exceed 2,000 characters")
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise ValueError("professional research dates are invalid")
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")

        selected_markets = _unique_selection(markets, "markets")
        allowed_markets = {option["key"] for option in PROFESSIONAL_MARKETS}
        if not selected_markets or any(market not in allowed_markets for market in selected_markets):
            raise ValueError("Unknown or empty professional market selection")
        selected_index_keys = _unique_selection(indices, "indices")
        if not selected_index_keys or len(selected_index_keys) > 6:
            raise ValueError("Select between 1 and 6 professional research indices")
        selected_indices = tuple(get_index(key) for key in selected_index_keys)
        if any(index is None for index in selected_indices):
            raise ValueError("Unknown professional research index")
        reviewed_indices = tuple(index for index in selected_indices if index is not None)
        if any(index.market_key not in selected_markets for index in reviewed_indices):
            raise ValueError("Every selected index must belong to a selected market")
        selected_metrics = _unique_selection(metrics, "metrics")
        if not selected_metrics or any(metric not in PROFESSIONAL_METRIC_KEYS for metric in selected_metrics):
            raise ValueError("Unknown or empty professional research metric selection")

        index_names = "、".join(index.display_name for index in reviewed_indices)
        retrieval_query = (
            f"专业版多指数研究：{index_names}；区间 {start_date.isoformat()} 至 {end_date.isoformat()}；"
            f"指标 {', '.join(selected_metrics)}。{notes}"
        )
        log_event(
            "professional_research_started",
            index_count=len(reviewed_indices),
            market_count=len(selected_markets),
            metric_count=len(selected_metrics),
        )
        language_context = self._retrieve(retrieval_query)

        snapshots: list[dict[str, object]] = []
        with ThreadPoolExecutor(
            max_workers=min(4, len(reviewed_indices)),
            thread_name_prefix="professional-index",
        ) as executor:
            futures = [
                executor.submit(
                    copy_context().run,
                    self._index_research.overview,
                    index,
                    start_date=start_date,
                    end_date=end_date,
                    metrics=selected_metrics,
                )
                for index in reviewed_indices
            ]
            snapshots.extend(future.result() for future in futures)

        reply = WebAgentReply(
            conversation_id=normalized_id,
            text=_professional_research_summary(snapshots),
            tool_calls=(),
            language_context=language_context.to_dict(),
            analysis_completed_at=_analysis_completed_at(),
            analysis_duration_ms=elapsed_milliseconds(started_at),
            response_kind="professional_index_comparison",
            research_period={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "assumptions": ["专业版使用用户明确选择的日期，不再推断模糊时间范围。"],
            },
            snapshot={
                "markets": list(selected_markets),
                "indices": list(selected_index_keys),
                "metrics": list(selected_metrics),
                "notes_supplied": bool(notes),
            },
            snapshots=tuple(snapshots),
        )
        log_event(
            "professional_research_completed",
            index_count=len(snapshots),
            duration_ms=reply.analysis_duration_ms,
        )
        return reply


def _conversation_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 80 or not normalized.replace("-", "").replace("_", "").isalnum():
        raise ValueError("conversation_id must contain only letters, numbers, hyphens, and underscores")
    return normalized


def _unique_selection(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"{field_name} must be a tuple of strings")
    return tuple(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))


def _professional_research_summary(snapshots: list[dict[str, object]]) -> str:
    """Create an evidence-only comparison sentence without a secondary model call."""

    ranked: list[tuple[float, str]] = []
    market_metrics_requested = False
    for snapshot in snapshots:
        selected_metrics = snapshot.get("selected_metrics")
        if not isinstance(selected_metrics, list):
            continue
        market_metrics_requested = market_metrics_requested or any(
            metric in {"market_data", "period_performance", "market_sentiment"}
            for metric in selected_metrics
        )
        if "period_performance" not in selected_metrics:
            continue
        index = snapshot.get("index")
        market_data = snapshot.get("market_data")
        if not isinstance(index, dict) or not isinstance(market_data, dict):
            continue
        performance = market_data.get("period_performance")
        if market_data.get("status") != "complete" or not isinstance(performance, dict):
            continue
        try:
            change_percent = float(str(performance["change_percent"]))
        except (KeyError, TypeError, ValueError):
            continue
        ranked.append((change_percent, str(index.get("display_name", "指数"))))

    base = f"已完成 {len(snapshots)} 个指数的专业版对比研究"
    if not ranked:
        if not market_metrics_requested:
            return f"{base}；本次仅返回勾选的静态风格、成分边界或风险信息，未发起行情请求。"
        return f"{base}；所选静态风格、成分边界与风险信息已按需返回，区间行情不可用时不会补写。"
    ranked.sort()
    weakest_change, weakest_name = ranked[0]
    strongest_change, strongest_name = ranked[-1]
    if len(ranked) == 1:
        return f"{base}；{strongest_name} 在实际覆盖交易日内涨跌幅为 {strongest_change:+.2f}%."
    return (
        f"{base}；在取得区间行情的指数中，{strongest_name}表现相对最高（{strongest_change:+.2f}%），"
        f"{weakest_name}相对最低（{weakest_change:+.2f}%）。该排序只比较所选区间价格表现。"
    )


def _analysis_completed_at() -> str:
    return datetime.now(timezone.utc).isoformat()

