"""Read-only execution of deterministic security-analysis plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from typing import Any

from .analysis_tags import AnalysisScenario, DataSourceTag
from .research_planning import SecurityAnalysisPlan, SecurityAnalysisRequest, SourceRoute, build_security_analysis_plan
from .tools import ToolRegistry


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One bounded source response, retaining provenance required for research review."""

    source: str
    priority: int
    raw_tool: str
    retrieved_at: str
    source_timestamp: str | int | None
    freshness_tag: str
    data: object

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "priority": self.priority,
            "raw_tool": self.raw_tool,
            "retrieved_at": self.retrieved_at,
            "source_timestamp": self.source_timestamp,
            "freshness_tag": self.freshness_tag,
            "data": self.data,
        }


@dataclass(frozen=True, slots=True)
class ExecutionError:
    """A safe per-source failure that allows deterministic fallback."""

    source: str
    priority: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {"source": self.source, "priority": self.priority, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class RiskFlag:
    """A deterministic warning; it is not a trade recommendation."""

    risk_id: str
    severity: str
    trigger: str
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "risk_id": self.risk_id,
            "severity": self.severity,
            "trigger": self.trigger,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class SecurityAnalysisResult:
    """Version-one read-only research result contract produced by the data executor."""

    plan: SecurityAnalysisPlan
    status: str
    evidence: tuple[EvidenceRecord, ...]
    risk_flags: tuple[RiskFlag, ...]
    execution_errors: tuple[ExecutionError, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": "security-analysis-result/v1",
            "status": self.status,
            "plan": self.plan.to_dict(),
            "evidence": [record.to_dict() for record in self.evidence],
            "risk_flags": [flag.to_dict() for flag in self.risk_flags],
            "execution_errors": [error.to_dict() for error in self.execution_errors],
            "conclusion": None,
            "disclaimer": "Read-only research data only; this result is not investment advice or a trade instruction.",
        }


class SecurityAnalysisExecutor:
    """Call only planned local tools and preserve every source-selection decision."""

    def __init__(self, tools: ToolRegistry) -> None:
        self._tools = tools
        self._available_tool_names = {tool.name for tool in tools.definitions()}

    def execute(
        self,
        request: SecurityAnalysisRequest,
        *,
        provider: str = "codex",
    ) -> SecurityAnalysisResult:
        """Execute the plan until its evidence threshold is met or routes are exhausted."""

        plan = build_security_analysis_plan(request, provider=provider)
        evidence: list[EvidenceRecord] = []
        errors: list[ExecutionError] = []
        for source in (plan.primary_source, *plan.fallback_sources):
            if len(evidence) >= plan.required_successful_sources:
                break
            try:
                tool_name, arguments = _tool_request(source, request)
            except ValueError as error:
                errors.append(ExecutionError(source.name, source.priority, str(error)))
                continue
            if tool_name not in self._available_tool_names:
                errors.append(
                    ExecutionError(
                        source.name,
                        source.priority,
                        f"planned tool '{tool_name}' is unavailable; configure this source before executing the plan",
                    )
                )
                continue
            try:
                raw_result = self._tools.execute(tool_name, arguments)
            except Exception:  # Tool implementations are external I/O boundaries.
                errors.append(
                    ExecutionError(
                        source.name,
                        source.priority,
                        "planned tool raised an unexpected execution error",
                    )
                )
                continue
            if not isinstance(raw_result, str):
                errors.append(
                    ExecutionError(
                        source.name,
                        source.priority,
                        "planned tool returned an invalid non-text response",
                    )
                )
                continue
            if raw_result.startswith("ERROR:"):
                errors.append(
                    ExecutionError(
                        source.name,
                        source.priority,
                        "configured data tool reported a failure; check source status and local service availability",
                    )
                )
                continue
            parsed_result = _parse_tool_result(raw_result)
            evidence.append(
                EvidenceRecord(
                    source=source.name,
                    priority=source.priority,
                    raw_tool=tool_name,
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    source_timestamp=_extract_source_timestamp(parsed_result),
                    freshness_tag=_freshness_tag(source),
                    data=parsed_result,
                )
            )
        risk_flags = _risk_flags(plan, evidence, errors)
        status = "complete" if len(evidence) >= plan.required_successful_sources else "incomplete"
        return SecurityAnalysisResult(plan, status, tuple(evidence), tuple(risk_flags), tuple(errors))


def _tool_request(source: SourceRoute, request: SecurityAnalysisRequest) -> tuple[str, dict[str, Any]]:
    scenario = request.scenario
    if source.name == "biying":
        if scenario is AnalysisScenario.SECURITY_LOOKUP:
            return "biying_market_data", {"action": "find_stocks", "query": request.symbol, "limit": 10}
        if scenario in {
            AnalysisScenario.A_SHARE_REALTIME_QUOTE,
            AnalysisScenario.A_SHARE_VALUATION_SNAPSHOT,
        }:
            return "biying_market_data", {"action": "realtime_quote", "code": request.symbol}
    if source.name == "aktools" and scenario in {
        AnalysisScenario.A_SHARE_PRICE_HISTORY,
        AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION,
        AnalysisScenario.RESEARCH_BRIEF,
    }:
        return "aktools_market_data", {
            "symbol": request.symbol,
            "start_date": _compact_date(request.start_date),
            "end_date": _compact_date(request.end_date),
            "period": "daily",
            "adjust": "",
            "limit": 120,
        }
    if source.name == "baostock" and scenario in {
        AnalysisScenario.A_SHARE_PRICE_HISTORY,
        AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION,
        AnalysisScenario.RESEARCH_BRIEF,
    }:
        return "baostock_market_data", {
            "code": _baostock_symbol(request.symbol),
            "start_date": _require_date(request.start_date),
            "end_date": _require_date(request.end_date),
            "frequency": "d",
            "adjustflag": "3",
            "limit": 120,
        }
    if source.name == "eodhd":
        if scenario is AnalysisScenario.SECURITY_LOOKUP:
            return "eodhd_market_data", {"action": "search", "query": request.symbol, "limit": 10}
        if scenario in {
            AnalysisScenario.GLOBAL_PRICE_HISTORY,
            AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION,
            AnalysisScenario.RESEARCH_BRIEF,
        }:
            return "eodhd_market_data", {
                "action": "historical_candles",
                "symbol": request.symbol,
                "start_date": _require_date(request.start_date),
                "end_date": _require_date(request.end_date),
                "period": "d",
                "limit": 120,
            }
    if source.name == "yfinance" and scenario in {
        AnalysisScenario.GLOBAL_PRICE_HISTORY,
        AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION,
        AnalysisScenario.RESEARCH_BRIEF,
    }:
        return "yfinance_market_data", {
            "symbol": _yahoo_symbol(request.symbol),
            "start_date": _require_date(request.start_date),
            "end_date": _exclusive_end_date(_require_date(request.end_date)),
            "interval": "1d",
            "auto_adjust": False,
            "limit": 120,
        }
    if source.name == "alphavantage":
        if scenario is AnalysisScenario.SECURITY_LOOKUP:
            return "alphavantage_market_data", {"action": "symbol_search", "keywords": request.symbol, "limit": 10}
        if scenario is AnalysisScenario.GLOBAL_MARKET_SNAPSHOT:
            return "alphavantage_market_data", {
                "action": "global_quote",
                "symbol": _alpha_vantage_symbol(request.symbol),
            }
        raise ValueError("this adapter cannot honor an exact historical date range")
    if source.name == "alltick":
        if scenario in {AnalysisScenario.A_SHARE_REALTIME_QUOTE, AnalysisScenario.GLOBAL_MARKET_SNAPSHOT}:
            return "alltick_market_data", {
                "action": "latest_quotes",
                "asset_class": "stock",
                "codes": [request.symbol],
            }
        raise ValueError("this adapter requires an AllTick product code and cannot honor an exact date range here")
    raise ValueError(f"no bounded adapter mapping is defined for scenario '{scenario.value}'")


def _parse_tool_result(raw_result: str) -> object:
    try:
        return json.loads(raw_result)
    except json.JSONDecodeError:
        return {"unstructured_result": raw_result}


def _extract_source_timestamp(payload: object) -> str | int | None:
    if not isinstance(payload, dict):
        return None
    for field in ("updated_at", "latest_trading_day", "timestamp_ms", "timestamp_seconds"):
        value = payload.get(field)
        if isinstance(value, (str, int)):
            return value
    quotes = payload.get("quotes")
    if isinstance(quotes, list) and quotes and isinstance(quotes[0], dict):
        timestamp = quotes[0].get("timestamp_ms")
        if isinstance(timestamp, (str, int)):
            return timestamp
    candles = payload.get("candles")
    if isinstance(candles, list) and candles and isinstance(candles[-1], dict):
        timestamp = candles[-1].get("date") or candles[-1].get("timestamp_seconds")
        if isinstance(timestamp, (str, int)):
            return timestamp
    return None


def _freshness_tag(source: SourceRoute) -> str:
    tags = set(source.tags)
    if DataSourceTag.REALTIME_QUOTE.value in tags:
        return "provider_reported_realtime"
    if DataSourceTag.END_OF_DAY_QUOTE.value in tags:
        return "end_of_day_or_delayed"
    if DataSourceTag.HISTORICAL_OHLCV.value in tags:
        return "historical"
    return "unspecified"


def _risk_flags(
    plan: SecurityAnalysisPlan,
    evidence: list[EvidenceRecord],
    errors: list[ExecutionError],
) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    if errors:
        flags.append(
            RiskFlag(
                "DATA_SOURCE_UNAVAILABLE",
                "warning",
                "One or more planned sources could not provide evidence.",
                tuple(error.source for error in errors),
            )
        )
    fallback_evidence = tuple(
        record.source
        for record in evidence
        if any(error.priority < record.priority for error in errors)
    )
    if fallback_evidence:
        flags.append(
            RiskFlag(
                "FALLBACK_SOURCE_USED",
                "warning",
                "The primary source was unavailable or unsuitable; a planned fallback supplied evidence.",
                fallback_evidence,
            )
        )
    if len(evidence) < plan.required_successful_sources:
        flags.append(
            RiskFlag(
                "INSUFFICIENT_EVIDENCE",
                "high",
                "The plan did not reach its required number of successful sources.",
                tuple(error.source for error in errors),
            )
        )
    non_realtime_evidence = tuple(
        record.source
        for record in evidence
        if record.freshness_tag in {"end_of_day_or_delayed", "historical"}
    )
    if non_realtime_evidence:
        flags.append(
            RiskFlag(
                "NON_REALTIME_DATA",
                "info",
                "At least one evidence record is end-of-day, delayed, or historical rather than provider-reported real-time.",
                non_realtime_evidence,
            )
        )
    return flags


def _compact_date(value: str | None) -> str:
    return _require_date(value).replace("-", "")


def _require_date(value: str | None) -> str:
    if value is None:
        raise ValueError("this scenario requires start_date and end_date")
    return value


def _exclusive_end_date(value: str) -> str:
    return (date.fromisoformat(value) + timedelta(days=1)).isoformat()


def _baostock_symbol(symbol: str) -> str:
    normalized = symbol.strip().lower()
    if normalized.startswith(("sh.", "sz.")):
        return normalized
    if len(normalized) == 6 and normalized.isdigit():
        return f"sh.{normalized}" if normalized.startswith(("5", "6", "9")) else f"sz.{normalized}"
    raise ValueError("BaoStock requires sh./sz. code or a six-digit A-share symbol")


def _yahoo_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    return normalized[:-3] if normalized.endswith(".US") else normalized


def _alpha_vantage_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    return normalized[:-3] if normalized.endswith(".US") else normalized
