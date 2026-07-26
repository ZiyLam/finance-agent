"""Deterministic scenario planning for bounded financial research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .analysis_tags import AnalysisScenario, DataSourceTag, Market, ModelTag
from .data_sources import DATA_SOURCE_CATALOG, DataSourceDefinition
from .model_catalog import MODEL_CATALOG, ModelDefinition, get_model_definition


@dataclass(frozen=True, slots=True)
class SecurityAnalysisRequest:
    """Version-one input contract for a single-security research request."""

    symbol: str
    market: Market
    scenario: AnalysisScenario
    start_date: str | None = None
    end_date: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be blank")
        has_start, has_end = self.start_date is not None, self.end_date is not None
        if has_start != has_end:
            raise ValueError("start_date and end_date must be provided together")
        if has_start:
            assert self.start_date is not None and self.end_date is not None
            try:
                start = date.fromisoformat(self.start_date)
                end = date.fromisoformat(self.end_date)
            except ValueError as error:
                raise ValueError("start_date and end_date must use YYYY-MM-DD") from error
            if start > end:
                raise ValueError("start_date cannot be after end_date")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "symbol": self.symbol,
            "market": self.market.value,
            "scenario": self.scenario.value,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


@dataclass(frozen=True, slots=True)
class ScenarioRule:
    """Tag requirements and explicit source preference for one research scenario."""

    scenario: AnalysisScenario
    allowed_markets: frozenset[Market]
    required_source_tags: frozenset[DataSourceTag]
    any_source_tags: frozenset[DataSourceTag] = frozenset()
    preferred_sources: tuple[str, ...] = ()
    minimum_sources: int = 1
    requires_date_range: bool = False
    required_model_tags: frozenset[ModelTag] = frozenset(
        {
            ModelTag.FINANCIAL_RESEARCH,
            ModelTag.STRUCTURED_RESPONSE,
            ModelTag.AGENT_TOOL_PROTOCOL,
        }
    )


SCENARIO_RULES = {
    AnalysisScenario.SECURITY_LOOKUP: ScenarioRule(
        AnalysisScenario.SECURITY_LOOKUP,
        frozenset({Market.A_SHARE, Market.GLOBAL}),
        frozenset({DataSourceTag.SYMBOL_SEARCH}),
        preferred_sources=("biying", "eodhd", "alphavantage"),
    ),
    AnalysisScenario.A_SHARE_REALTIME_QUOTE: ScenarioRule(
        AnalysisScenario.A_SHARE_REALTIME_QUOTE,
        frozenset({Market.A_SHARE}),
        frozenset({DataSourceTag.A_SHARE, DataSourceTag.REALTIME_QUOTE}),
        preferred_sources=("biying", "alltick"),
    ),
    AnalysisScenario.GLOBAL_MARKET_SNAPSHOT: ScenarioRule(
        AnalysisScenario.GLOBAL_MARKET_SNAPSHOT,
        frozenset({Market.GLOBAL, Market.MULTI_ASSET}),
        frozenset({DataSourceTag.GLOBAL_MARKETS}),
        frozenset({DataSourceTag.REALTIME_QUOTE, DataSourceTag.END_OF_DAY_QUOTE}),
        preferred_sources=("alltick", "alphavantage", "yfinance"),
    ),
    AnalysisScenario.A_SHARE_PRICE_HISTORY: ScenarioRule(
        AnalysisScenario.A_SHARE_PRICE_HISTORY,
        frozenset({Market.A_SHARE}),
        frozenset({DataSourceTag.A_SHARE, DataSourceTag.HISTORICAL_OHLCV}),
        preferred_sources=("aktools", "baostock", "alltick"),
        requires_date_range=True,
    ),
    AnalysisScenario.GLOBAL_PRICE_HISTORY: ScenarioRule(
        AnalysisScenario.GLOBAL_PRICE_HISTORY,
        frozenset({Market.GLOBAL, Market.MULTI_ASSET}),
        frozenset({DataSourceTag.GLOBAL_MARKETS, DataSourceTag.HISTORICAL_OHLCV}),
        preferred_sources=("eodhd", "yfinance", "alphavantage", "alltick"),
        requires_date_range=True,
    ),
    AnalysisScenario.A_SHARE_VALUATION_SNAPSHOT: ScenarioRule(
        AnalysisScenario.A_SHARE_VALUATION_SNAPSHOT,
        frozenset({Market.A_SHARE}),
        frozenset({DataSourceTag.A_SHARE, DataSourceTag.VALUATION_METRICS}),
        preferred_sources=("biying",),
    ),
    AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION: ScenarioRule(
        AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION,
        frozenset({Market.A_SHARE, Market.GLOBAL, Market.MULTI_ASSET}),
        frozenset({DataSourceTag.HISTORICAL_OHLCV}),
        preferred_sources=("aktools", "baostock", "eodhd", "yfinance", "alphavantage", "alltick"),
        minimum_sources=2,
        requires_date_range=True,
    ),
    AnalysisScenario.RESEARCH_BRIEF: ScenarioRule(
        AnalysisScenario.RESEARCH_BRIEF,
        frozenset({Market.A_SHARE, Market.GLOBAL, Market.MULTI_ASSET}),
        frozenset({DataSourceTag.HISTORICAL_OHLCV}),
        preferred_sources=("aktools", "eodhd", "baostock", "yfinance", "alphavantage", "alltick"),
        requires_date_range=True,
    ),
}


@dataclass(frozen=True, slots=True)
class SourceRoute:
    """One source selected by policy, with tags retained for auditability."""

    name: str
    display_name: str
    priority: int
    tags: tuple[str, ...]

    @classmethod
    def from_definition(cls, definition: DataSourceDefinition, priority: int) -> "SourceRoute":
        return cls(
            definition.name,
            definition.display_name,
            priority,
            tuple(sorted(tag.value for tag in definition.tags)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "priority": self.priority,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class ModelRoute:
    """One compatible model provider selected from its declared tags."""

    provider: str
    display_name: str
    tags: tuple[str, ...]

    @classmethod
    def from_definition(cls, definition: ModelDefinition) -> "ModelRoute":
        return cls(
            definition.provider,
            definition.display_name,
            tuple(sorted(tag.value for tag in definition.tags)),
        )

    def to_dict(self) -> dict[str, object]:
        return {"provider": self.provider, "display_name": self.display_name, "tags": list(self.tags)}


@dataclass(frozen=True, slots=True)
class SecurityAnalysisPlan:
    """Version-one standard planning output, ready for a future data executor."""

    request: SecurityAnalysisRequest
    primary_source: SourceRoute
    fallback_sources: tuple[SourceRoute, ...]
    model: ModelRoute
    required_successful_sources: int = 1
    required_evidence_fields: tuple[str, ...] = (
        "source",
        "retrieved_at",
        "source_timestamp",
        "freshness_tag",
        "raw_tool",
    )
    required_risk_fields: tuple[str, ...] = (
        "risk_id",
        "severity",
        "trigger",
        "evidence_refs",
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": "security-analysis-plan/v1",
            "request": self.request.to_dict(),
            "routing": {
                "primary_source": self.primary_source.to_dict(),
                "fallback_sources": [source.to_dict() for source in self.fallback_sources],
                "model": self.model.to_dict(),
                "required_successful_sources": self.required_successful_sources,
            },
            "required_evidence_fields": list(self.required_evidence_fields),
            "required_risk_fields": list(self.required_risk_fields),
            "execution_note": "This plan is deterministic and read-only; an executor must preserve source and freshness evidence.",
        }


def build_security_analysis_plan(
    request: SecurityAnalysisRequest,
    *,
    provider: str = "codex",
) -> SecurityAnalysisPlan:
    """Build a deterministic plan without invoking a provider or data source."""

    rule = SCENARIO_RULES[request.scenario]
    if request.market not in rule.allowed_markets:
        allowed = ", ".join(market.value for market in sorted(rule.allowed_markets, key=str))
        raise ValueError(f"scenario '{request.scenario.value}' supports only: {allowed}")
    if rule.requires_date_range and (request.start_date is None or request.end_date is None):
        raise ValueError(f"scenario '{request.scenario.value}' requires start_date and end_date")

    sources = _route_sources(rule, request.market)
    if len(sources) < rule.minimum_sources:
        raise RuntimeError(
            f"scenario '{request.scenario.value}' requires {rule.minimum_sources} sources but only {len(sources)} match"
        )
    model = get_model_definition(provider)
    if model is None:
        raise ValueError(f"unknown model provider: {provider}")
    missing_model_tags = rule.required_model_tags - model.tags
    if missing_model_tags:
        missing = ", ".join(sorted(tag.value for tag in missing_model_tags))
        raise ValueError(
            f"model provider '{provider}' is not suitable for '{request.scenario.value}'; missing tags: {missing}"
        )
    return SecurityAnalysisPlan(
        request=request,
        primary_source=sources[0],
        fallback_sources=tuple(sources[1:]),
        model=ModelRoute.from_definition(model),
        required_successful_sources=rule.minimum_sources,
    )


def _route_sources(rule: ScenarioRule, market: Market) -> tuple[SourceRoute, ...]:
    eligible = [
        definition
        for definition in DATA_SOURCE_CATALOG
        if _source_matches_rule(definition, rule, market)
    ]
    by_name = {definition.name: definition for definition in eligible}
    ordered: list[DataSourceDefinition] = []
    for name in rule.preferred_sources:
        if (definition := by_name.pop(name, None)) is not None:
            ordered.append(definition)
    ordered.extend(definition for definition in eligible if definition.name in by_name)
    return tuple(SourceRoute.from_definition(definition, index + 1) for index, definition in enumerate(ordered))


def _source_matches_rule(definition: DataSourceDefinition, rule: ScenarioRule, market: Market) -> bool:
    required_tags = rule.required_source_tags | {_market_tag(market)}
    if not required_tags.issubset(definition.tags):
        return False
    return not rule.any_source_tags or bool(rule.any_source_tags & definition.tags)


def _market_tag(market: Market) -> DataSourceTag:
    return {
        Market.A_SHARE: DataSourceTag.A_SHARE,
        Market.GLOBAL: DataSourceTag.GLOBAL_MARKETS,
        Market.MULTI_ASSET: DataSourceTag.MULTI_ASSET,
    }[market]


def catalog_snapshot() -> dict[str, object]:
    """Return source/model tags in a JSON-ready form without reading credentials."""

    return {
        "data_sources": [
            {
                "name": definition.name,
                "display_name": definition.display_name,
                "tags": sorted(tag.value for tag in definition.tags),
            }
            for definition in DATA_SOURCE_CATALOG
            if definition.tags
        ],
        "models": [
            {
                "provider": definition.provider,
                "display_name": definition.display_name,
                "tags": sorted(tag.value for tag in definition.tags),
                "configuration_note": definition.configuration_note,
            }
            for definition in MODEL_CATALOG
        ],
        "scenarios": [
            {
                "scenario": rule.scenario.value,
                "markets": sorted(market.value for market in rule.allowed_markets),
                "requires_date_range": rule.requires_date_range,
            }
            for rule in SCENARIO_RULES.values()
        ],
    }
