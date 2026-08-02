"""Resolve reviewed indices and build evidence-bounded research snapshots."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date

from .beginner_research import BeginnerResearchService

# Keep the original import surface stable while static metadata lives in its own module.
from .index_catalog import (
    CAC_40,
    CHINEXT,
    CSI_300,
    CSI_500,
    CSI_1000,
    DAX,
    DOW_JONES,
    FTSE_100,
    HANG_SENG,
    HANG_SENG_TECH,
    INDEX_CATALOG,
    INDEXES_BY_KEY,
    NASDAQ_100,
    NASDAQ_COMPOSITE,
    NIKKEI_225,
    PROFESSIONAL_MARKETS,
    PROFESSIONAL_METRIC_KEYS,
    PROFESSIONAL_METRICS,
    RUSSELL_2000,
    SP_500,
    SSE_50,
    SSE_COMPOSITE,
    SZSE_COMPONENT,
    IndexDefinition,
    get_index,
    professional_research_catalog,
)

__all__ = [
    "CAC_40",
    "CHINEXT",
    "CSI_1000",
    "CSI_300",
    "CSI_500",
    "DAX",
    "DOW_JONES",
    "FTSE_100",
    "HANG_SENG",
    "HANG_SENG_TECH",
    "INDEX_CATALOG",
    "INDEXES_BY_KEY",
    "NASDAQ_100",
    "NASDAQ_COMPOSITE",
    "NIKKEI_225",
    "PROFESSIONAL_MARKETS",
    "PROFESSIONAL_METRIC_KEYS",
    "PROFESSIONAL_METRICS",
    "RUSSELL_2000",
    "SP_500",
    "SSE_50",
    "SSE_COMPOSITE",
    "SZSE_COMPONENT",
    "IndexDefinition",
    "IndexResearchService",
    "IndexResolver",
    "get_index",
    "professional_research_catalog",
]

_MARKET_DATA_METRICS = frozenset(
    {"market_data", "period_performance", "market_sentiment"}
)


class IndexResolver:
    """Resolve a reviewed index before invoking the general-purpose Agent."""

    def resolve(self, query: str) -> IndexDefinition | None:
        normalized = re.sub(r"\s+", " ", query.casefold()).strip()
        if not normalized:
            return None

        matches = [
            (len(alias.casefold()), -position, definition)
            for position, definition in enumerate(INDEX_CATALOG)
            for alias in definition.aliases
            if alias.casefold() in normalized
        ]
        best_match = max(matches, key=lambda match: (match[0], match[1]), default=None)
        return best_match[2] if best_match is not None else None


class IndexResearchService:
    """Build a complete index-oriented answer from one bounded market-data read."""

    def __init__(self, beginner_research: BeginnerResearchService) -> None:
        self._beginner_research = beginner_research

    def overview(
        self,
        index: IndexDefinition,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        metrics: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        """Return market, historical, style, industry, and risk sections in one response."""

        selected_metrics = (
            tuple(option["key"] for option in PROFESSIONAL_METRICS)
            if metrics is None
            else metrics
        )
        if not selected_metrics or any(
            metric not in PROFESSIONAL_METRIC_KEYS for metric in selected_metrics
        ):
            raise ValueError("Unknown or empty professional research metric selection")
        if (start_date is None) != (end_date is None):
            raise ValueError("start_date and end_date must be provided together")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")

        market_data: dict[str, object] | None = None
        if _MARKET_DATA_METRICS.intersection(selected_metrics):
            price_snapshot = (
                self._beginner_research.period(
                    index.as_security(),
                    start_date=start_date,
                    end_date=end_date,
                ).to_dict()
                if start_date is not None and end_date is not None
                else self._beginner_research.latest_week(index.as_security()).to_dict()
            )
            market_data = price_snapshot["market_data"]  # type: ignore[assignment]

        result: dict[str, object] = {
            "contract_version": "index-research-snapshot/v1",
            "index": index.to_dict(),
            "default_scope": (
                f"精确区间 {start_date.isoformat()} 至 {end_date.isoformat()}"
                if start_date is not None and end_date is not None
                else "近期行情、最近五个交易日历史表现、风格/估值边界、成分行业边界与风险"
            ),
            "selected_metrics": list(selected_metrics),
            "limitations": [
                "所选行情类指标共用一次日线读取，不会为不同展示区块重复请求数据。",
                "指数成分、行业权重和估值属于会变化的数据；未接入权威源时会明确保留为空，而不补写。",
                "本结果仅用于个人研究与内容整理，不构成投资建议或交易指令。",
            ],
        }
        if market_data is not None:
            result["market_data"] = market_data
        if "market_sentiment" in selected_metrics:
            result["market_sentiment"] = _index_market_sentiment(market_data)
        if "valuation_style" in selected_metrics:
            result["valuation_style"] = {
                "status": "reference_profile",
                "style": index.style_profile,
                "valuation": "未接入指数实时估值数据；不会推断当前市盈率、市净率或估值分位。",
            }
        if "constituent_industries" in selected_metrics:
            result["constituent_industries"] = {
                "status": "reference_profile",
                "methodology": index.methodology_note,
                "industry_note": index.industry_note,
            }
        if "risks" in selected_metrics:
            result["risks"] = list(index.risk_notes)
        return result


def _index_market_sentiment(market_data: object) -> dict[str, str]:
    """Describe only the index's recent price tone, never a whole-market claim."""

    if not isinstance(market_data, Mapping) or market_data.get("status") != "complete":
        return {
            "status": "unavailable",
            "label": "待行情数据",
            "tone": "flat",
            "basis": "行情数据不可用，未生成指数表现情绪。",
        }

    performance = market_data.get("period_performance") or market_data.get("recent_week")
    if not isinstance(performance, Mapping):
        return {
            "status": "unavailable",
            "label": "待行情数据",
            "tone": "flat",
            "basis": "未返回最近交易日汇总，未生成指数表现情绪。",
        }
    try:
        change_percent = float(str(performance["change_percent"]))
    except (KeyError, TypeError, ValueError):
        return {
            "status": "unavailable",
            "label": "待行情数据",
            "tone": "flat",
            "basis": "未返回可用涨跌幅，未生成指数表现情绪。",
        }

    if change_percent >= 1:
        label, tone = "偏强", "up"
    elif change_percent <= -1:
        label, tone = "偏弱", "down"
    else:
        label, tone = "中性", "flat"
    return {
        "status": "derived_from_index_return",
        "label": label,
        "tone": tone,
        "basis": f"仅根据本指数所选区间涨跌幅 {change_percent:+.2f}% 推导，不代表全市场情绪。",
    }
