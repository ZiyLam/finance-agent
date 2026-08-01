"""Stable capability tags used by source and model routing."""

from __future__ import annotations

from enum import StrEnum


class DataSourceTag(StrEnum):
    """Capabilities actually exposed by the current data-source adapters."""

    A_SHARE = "a_share"
    GLOBAL_MARKETS = "global_markets"
    MULTI_ASSET = "multi_asset"
    SYMBOL_SEARCH = "symbol_search"
    REALTIME_QUOTE = "realtime_quote"
    END_OF_DAY_QUOTE = "end_of_day_quote"
    HISTORICAL_OHLCV = "historical_ohlcv"
    DATE_BOUNDED_HISTORICAL = "date_bounded_historical"
    VALUATION_METRICS = "valuation_metrics"
    LOCAL_SERVICE = "local_service"


class ModelTag(StrEnum):
    """Capabilities used to decide whether a model is suitable for a scenario."""

    FINANCIAL_RESEARCH = "financial_research"
    CHINESE = "chinese"
    STRUCTURED_RESPONSE = "structured_response"
    AGENT_TOOL_PROTOCOL = "agent_tool_protocol"
    LOCAL_SELF_TEST = "local_self_test"
    REMOTE_API = "remote_api"
    OFFLINE_SMOKE_TEST = "offline_smoke_test"


class Market(StrEnum):
    """Canonical market groups understood by the initial research planner."""

    A_SHARE = "a_share"
    GLOBAL = "global"
    MULTI_ASSET = "multi_asset"


class AnalysisScenario(StrEnum):
    """Bounded research scenarios supported by deterministic source routing."""

    SECURITY_LOOKUP = "security_lookup"
    A_SHARE_REALTIME_QUOTE = "a_share_realtime_quote"
    GLOBAL_MARKET_SNAPSHOT = "global_market_snapshot"
    A_SHARE_PRICE_HISTORY = "a_share_price_history"
    GLOBAL_PRICE_HISTORY = "global_price_history"
    A_SHARE_VALUATION_SNAPSHOT = "a_share_valuation_snapshot"
    CROSS_SOURCE_HISTORY_VALIDATION = "cross_source_history_validation"
    RESEARCH_BRIEF = "research_brief"
