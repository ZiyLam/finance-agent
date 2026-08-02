"""Evidence-bound market-data research reports for a single security.

This module deliberately performs deterministic calculations only.  It turns
the executor's source-preserving result into a reviewable report, but it does
not invent company fundamentals, news, filings, or a buy/sell instruction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from statistics import stdev
from typing import Iterable

from .analysis_execution import EvidenceRecord, RiskFlag, SecurityAnalysisResult

EVIDENCE_GRADE = "B"
"""Current adapters are third-party/public market-data sources, not filings."""


@dataclass(frozen=True, slots=True)
class ReportRiskFlag:
    """A report-level risk with a deterministic trigger and evidence references."""

    risk_id: str
    color: str
    severity: str
    trigger: str
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "risk_id": self.risk_id,
            "color": self.color,
            "severity": self.severity,
            "trigger": self.trigger,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class SecurityResearchReport:
    """Version-one report contract derived entirely from an analysis result."""

    analysis_result: SecurityAnalysisResult
    confidence: str
    summary: str
    market_observations: tuple[dict[str, object], ...]
    market_snapshots: tuple[dict[str, object], ...]
    cross_source_checks: tuple[dict[str, object], ...]
    scenarios: tuple[dict[str, str], ...]
    risk_flags: tuple[ReportRiskFlag, ...]
    limitations: tuple[str, ...]
    next_research_actions: tuple[str, ...]
    report_markdown: str

    def to_dict(self) -> dict[str, object]:
        request = self.analysis_result.plan.request
        return {
            "contract_version": "security-research-report/v1",
            "scope": {
                "symbol": request.symbol,
                "market": request.market.value,
                "scenario": request.scenario.value,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "currency": "not_confirmed_by_current_evidence",
                "evidence_grade_policy": "Current market-data adapters are classified B; no primary filing evidence is present.",
            },
            "report_status": self.analysis_result.status,
            "confidence": self.confidence,
            "summary": self.summary,
            "market_observations": list(self.market_observations),
            "market_snapshots": list(self.market_snapshots),
            "cross_source_checks": list(self.cross_source_checks),
            "scenarios": list(self.scenarios),
            "risk_flags": [flag.to_dict() for flag in self.risk_flags],
            "limitations": list(self.limitations),
            "next_research_actions": list(self.next_research_actions),
            "evidence": [record.to_dict() for record in self.analysis_result.evidence],
            "execution_errors": [error.to_dict() for error in self.analysis_result.execution_errors],
            "report_markdown": self.report_markdown,
            "disclaimer": "For research and education only. This is not personalized investment advice or a trade instruction; investing involves risk.",
        }


@dataclass(frozen=True, slots=True)
class _ParsedPriceSeries:
    observation: dict[str, object]
    closes_by_date: dict[str, Decimal]


class SecurityResearchReportBuilder:
    """Build a cautious research report from already collected evidence."""

    def build(self, analysis_result: SecurityAnalysisResult) -> SecurityResearchReport:
        parsed_series = tuple(
            series
            for index, evidence in enumerate(analysis_result.evidence, start=1)
            if (series := _parse_price_series(evidence, index)) is not None
        )
        observations = tuple(series.observation for series in parsed_series)
        snapshots = tuple(
            snapshot
            for index, evidence in enumerate(analysis_result.evidence, start=1)
            if (snapshot := _parse_market_snapshot(evidence, index)) is not None
        )
        cross_source_checks = _cross_source_checks(parsed_series)
        risks = _build_risk_flags(analysis_result, observations, cross_source_checks)
        confidence = _confidence(analysis_result, observations, cross_source_checks)
        summary = _summary(analysis_result, observations, confidence)
        scenarios = _scenarios(observations)
        limitations = _limitations(analysis_result, observations, cross_source_checks)
        next_actions = _next_actions(cross_source_checks)
        report = SecurityResearchReport(
            analysis_result=analysis_result,
            confidence=confidence,
            summary=summary,
            market_observations=observations,
            market_snapshots=snapshots,
            cross_source_checks=cross_source_checks,
            scenarios=scenarios,
            risk_flags=risks,
            limitations=limitations,
            next_research_actions=next_actions,
            report_markdown="",
        )
        return SecurityResearchReport(
            analysis_result=report.analysis_result,
            confidence=report.confidence,
            summary=report.summary,
            market_observations=report.market_observations,
            market_snapshots=report.market_snapshots,
            cross_source_checks=report.cross_source_checks,
            scenarios=report.scenarios,
            risk_flags=report.risk_flags,
            limitations=report.limitations,
            next_research_actions=report.next_research_actions,
            report_markdown=_render_markdown(report),
        )


def _parse_price_series(evidence: EvidenceRecord, index: int) -> _ParsedPriceSeries | None:
    if not isinstance(evidence.data, dict):
        return None
    candles = evidence.data.get("candles")
    if not isinstance(candles, list):
        return None

    rows: dict[str, dict[str, Decimal | None]] = {}
    for candle in candles:
        if not isinstance(candle, dict):
            continue
        date_value = candle.get("date")
        close = _decimal(candle.get("close"))
        if not isinstance(date_value, str) or close is None:
            continue
        rows[date_value] = {
            "close": close,
            "high": _decimal(candle.get("high")) or close,
            "low": _decimal(candle.get("low")) or close,
            "volume": _decimal(candle.get("volume")),
        }
    if not rows:
        return None

    ordered_dates = sorted(rows)
    ordered_rows = [rows[item] for item in ordered_dates]
    closes = [row["close"] for row in ordered_rows]
    assert all(isinstance(close, Decimal) for close in closes)
    close_values = [close for close in closes if isinstance(close, Decimal)]
    highs = [row["high"] for row in ordered_rows if isinstance(row["high"], Decimal)]
    lows = [row["low"] for row in ordered_rows if isinstance(row["low"], Decimal)]
    volumes = [row["volume"] for row in ordered_rows if isinstance(row["volume"], Decimal)]
    start_close, end_close = close_values[0], close_values[-1]
    observation = {
        "evidence_ref": _evidence_ref(index),
        "source": evidence.source,
        "evidence_grade": EVIDENCE_GRADE,
        "source_timestamp": evidence.source_timestamp,
        "freshness_tag": evidence.freshness_tag,
        "reported_period": _reported_period(evidence.data),
        "reported_adjustment": _reported_adjustment(evidence.data),
        "sample_size": len(close_values),
        "first_date": ordered_dates[0],
        "last_date": ordered_dates[-1],
        "start_close": _number(start_close),
        "end_close": _number(end_close),
        "period_return_percent": _percent_change(start_close, end_close),
        "period_high": _number(max(highs)) if highs else None,
        "period_low": _number(min(lows)) if lows else None,
        "max_drawdown_percent": _max_drawdown(close_values),
        "annualized_volatility_percent": _annualized_volatility(close_values),
        "average_volume": _number(sum(volumes) / len(volumes)) if volumes else None,
        "price_trend": _price_trend(_percent_change(start_close, end_close)),
    }
    return _ParsedPriceSeries(observation=observation, closes_by_date=dict(zip(ordered_dates, close_values)))


def _parse_market_snapshot(evidence: EvidenceRecord, index: int) -> dict[str, object] | None:
    if not isinstance(evidence.data, dict) or "candles" in evidence.data:
        return None
    price = _decimal(evidence.data.get("price"))
    if price is None:
        return None
    snapshot: dict[str, object] = {
        "evidence_ref": _evidence_ref(index),
        "source": evidence.source,
        "evidence_grade": EVIDENCE_GRADE,
        "source_timestamp": evidence.source_timestamp,
        "freshness_tag": evidence.freshness_tag,
        "price": _number(price),
    }
    for field in ("change_percent", "dynamic_pe", "pb", "volume_lots", "volume"):
        value = _decimal(evidence.data.get(field))
        if value is not None:
            snapshot[field] = _number(value)
    return snapshot


def _cross_source_checks(series: tuple[_ParsedPriceSeries, ...]) -> tuple[dict[str, object], ...]:
    checks: list[dict[str, object]] = []
    for first_index, first in enumerate(series):
        for second in series[first_index + 1 :]:
            shared_dates = sorted(set(first.closes_by_date) & set(second.closes_by_date))
            differences = [
                _relative_difference_percent(first.closes_by_date[item], second.closes_by_date[item])
                for item in shared_dates
            ]
            numeric_differences = [item for item in differences if item is not None]
            if not numeric_differences:
                continue
            max_difference = max(numeric_differences)
            checks.append(
                {
                    "sources": [first.observation["source"], second.observation["source"]],
                    "evidence_refs": [first.observation["evidence_ref"], second.observation["evidence_ref"]],
                    "overlapping_dates": len(numeric_differences),
                    "mean_absolute_close_difference_percent": round(
                        sum(numeric_differences) / len(numeric_differences), 4
                    ),
                    "max_absolute_close_difference_percent": round(max_difference, 4),
                    "status": "consistent" if max_difference <= 1.0 else "requires_review",
                    "method_note": "Compared unadjusted close values on identical calendar dates; corporate-action and provider methodology differences still require review.",
                }
            )
    return tuple(checks)


def _build_risk_flags(
    result: SecurityAnalysisResult,
    observations: tuple[dict[str, object], ...],
    checks: tuple[dict[str, object], ...],
) -> tuple[ReportRiskFlag, ...]:
    flags = [_execution_risk_flag(flag) for flag in result.risk_flags]
    flags.append(
        ReportRiskFlag(
            "FUNDAMENTAL_EVIDENCE_MISSING",
            "yellow",
            "warning",
            "Current evidence is market-data only; no filings, financial statements, company disclosures, or primary regulatory sources were supplied.",
            tuple(item["evidence_ref"] for item in observations),
        )
    )
    if not observations:
        flags.append(
            ReportRiskFlag(
                "USABLE_PRICE_HISTORY_MISSING",
                "red",
                "high",
                "No usable date-and-close price series was available for quantitative market analysis.",
                (),
            )
        )
    maximum_drawdown = min(
        (
            item["max_drawdown_percent"]
            for item in observations
            if isinstance(item.get("max_drawdown_percent"), (int, float))
        ),
        default=None,
    )
    if isinstance(maximum_drawdown, (int, float)) and maximum_drawdown <= -20:
        color, severity = ("red", "high") if maximum_drawdown <= -40 else ("yellow", "warning")
        flags.append(
            ReportRiskFlag(
                "ELEVATED_HISTORICAL_DRAWDOWN",
                color,
                severity,
                f"Observed maximum close-to-close drawdown was {maximum_drawdown:.2f}% in the returned sample.",
                tuple(
                    item["evidence_ref"]
                    for item in observations
                    if item.get("max_drawdown_percent") == maximum_drawdown
                ),
            )
        )
    maximum_volatility = max(
        (
            item["annualized_volatility_percent"]
            for item in observations
            if isinstance(item.get("annualized_volatility_percent"), (int, float))
        ),
        default=None,
    )
    if isinstance(maximum_volatility, (int, float)) and maximum_volatility >= 40:
        color, severity = ("red", "high") if maximum_volatility >= 70 else ("yellow", "warning")
        flags.append(
            ReportRiskFlag(
                "ELEVATED_HISTORICAL_VOLATILITY",
                color,
                severity,
                f"Annualized close-to-close volatility was {maximum_volatility:.2f}% in the returned sample.",
                tuple(
                    item["evidence_ref"]
                    for item in observations
                    if item.get("annualized_volatility_percent") == maximum_volatility
                ),
            )
        )
    for check in checks:
        if check["status"] == "requires_review":
            flags.append(
                ReportRiskFlag(
                    "CROSS_SOURCE_CLOSE_DIVERGENCE",
                    "yellow",
                    "warning",
                    "The maximum same-date close difference exceeded the 1.00% review threshold.",
                    tuple(str(item) for item in check["evidence_refs"]),
                )
            )
    return tuple(flags)


def _execution_risk_flag(flag: RiskFlag) -> ReportRiskFlag:
    color = "red" if flag.severity == "high" else "yellow" if flag.severity == "warning" else "info"
    return ReportRiskFlag(flag.risk_id, color, flag.severity, flag.trigger, flag.evidence_refs)


def _confidence(
    result: SecurityAnalysisResult,
    observations: tuple[dict[str, object], ...],
    checks: tuple[dict[str, object], ...],
) -> str:
    if result.status != "complete" or not observations:
        return "low"
    if any(check["status"] == "requires_review" for check in checks):
        return "low"
    if any(check["status"] == "consistent" for check in checks):
        return "medium"
    return "low"


def _summary(
    result: SecurityAnalysisResult,
    observations: tuple[dict[str, object], ...],
    confidence: str,
) -> str:
    if not observations:
        return "No usable historical price series was returned, so the report cannot form a market-data observation."
    primary = observations[0]
    return_value = primary.get("period_return_percent")
    return_text = f"{return_value:.2f}%" if isinstance(return_value, (int, float)) else "not calculable"
    return (
        f"Based on {primary['source']} historical market data from {primary['first_date']} to "
        f"{primary['last_date']}, the observed price trend was {primary['price_trend']} with a "
        f"period return of {return_text}. Confidence is {confidence} because current evidence "
        "does not include primary fundamental or disclosure evidence."
    )


def _scenarios(observations: tuple[dict[str, object], ...]) -> tuple[dict[str, str], ...]:
    if not observations:
        return (
            {
                "name": "evidence_gap",
                "trigger": "Obtain a verified historical price series and primary company evidence.",
                "research_implication": "No price-based scenario can be evaluated from the current evidence.",
            },
        )
    primary = observations[0]
    high, low = primary.get("period_high"), primary.get("period_low")
    levels_known = isinstance(high, (int, float)) and isinstance(low, (int, float))
    return (
        {
            "name": "base",
            "trigger": "Prices remain within the observed sample range and no new primary evidence changes the research thesis.",
            "research_implication": "Treat the historical range as context only; verify business, valuation, and event evidence before drawing a broader conclusion.",
        },
        {
            "name": "constructive",
            "trigger": f"A close above the observed sample high of {high}." if levels_known else "A verified improvement in subsequent market and primary evidence.",
            "research_implication": "Check whether volume, disclosures, and independent sources support the move rather than treating price alone as confirmation.",
        },
        {
            "name": "stress",
            "trigger": f"A close below the observed sample low of {low}." if levels_known else "New evidence of material operating, liquidity, governance, or regulatory stress.",
            "research_implication": "Reassess the evidence set, liquidity conditions, and thesis assumptions; historical price levels do not limit future losses.",
        },
    )


def _limitations(
    result: SecurityAnalysisResult,
    observations: tuple[dict[str, object], ...],
    checks: tuple[dict[str, object], ...],
) -> tuple[str, ...]:
    limitations = [
        "All current market-data observations are evidence grade B. No primary filings, earnings releases, company disclosures, or regulatory records were collected.",
        "Currency, exchange, corporate-action treatment, and adjustment methodology are not independently confirmed by this report.",
        "Historical market prices cannot establish business quality, valuation adequacy, future returns, or suitability for any investor.",
    ]
    if result.status != "complete":
        limitations.append("The planned evidence threshold was not reached; review execution errors before relying on any observation.")
    if len(observations) < 2 or not checks:
        limitations.append("No same-date independent cross-source close comparison was available for the returned price series.")
    return tuple(limitations)


def _next_actions(checks: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    actions = [
        "Retrieve and review primary company filings, earnings releases, and regulatory disclosures for the same analysis period.",
        "Verify the security identifier, exchange, currency, and corporate-action/adjustment convention with an independent source.",
        "Compare revenue growth, margins, cash flow, leverage, and valuation assumptions with relevant peers before forming a fundamental view.",
        "Track the next earnings, disclosure, regulatory, and industry events as explicit thesis-validation triggers.",
    ]
    if any(check["status"] == "requires_review" for check in checks):
        actions.insert(0, "Reconcile cross-source close-price differences before using the series for return or drawdown conclusions.")
    return tuple(actions[:5])


def _render_markdown(report: SecurityResearchReport) -> str:
    request = report.analysis_result.plan.request
    lines = [
        "# 单标的市场数据研究报告",
        "",
        "## 1. 分析范围与数据截至时间",
        "",
        f"- 标的：{request.symbol}；市场：{request.market.value}；场景：{request.scenario.value}",
        f"- 区间：{request.start_date or '未提供'} 至 {request.end_date or '未提供'}；币种：未由当前证据确认",
        "- 证据等级：当前行情数据统一为 B 级（第三方/公共市场数据），并非公司披露或监管原始文件。",
        "",
        "## 2. 结论摘要",
        "",
        f"{report.summary}",
        "",
        "## 3. 证据与逻辑链",
        "",
    ]
    if report.market_observations:
        for item in report.market_observations:
            lines.append(
                "- "
                f"[{item['evidence_grade']}｜{item['source']}｜来源时间戳：{item['source_timestamp'] or '未提供'}] "
                f"{item['first_date']} 至 {item['last_date']}，收盘价 {item['start_close']} → {item['end_close']}，"
                f"区间收益 {item['period_return_percent']}%，最大回撤 {item['max_drawdown_percent']}%，"
                f"年化波动率 {item['annualized_volatility_percent']}%；周期 {item['reported_period']}，"
                f"复权/调整口径 {item['reported_adjustment']}。"
            )
    else:
        lines.append("- 未取得可用于计算的日期—收盘价序列。")
    if report.cross_source_checks:
        lines.append("")
        lines.append("### 跨源核验")
        lines.append("")
        for check in report.cross_source_checks:
            lines.append(
                f"- {' / '.join(str(item) for item in check['sources'])}：重叠 {check['overlapping_dates']} 个交易日，"
                f"最大收盘价差异 {check['max_absolute_close_difference_percent']}%，状态：{check['status']}。"
            )
    lines.extend(["", "## 4. 情景分析", ""])
    for scenario in report.scenarios:
        lines.append(f"- {scenario['name']}：触发器：{scenario['trigger']} 研究含义：{scenario['research_implication']}")
    lines.extend(["", "## 5. 风险提醒", ""])
    for risk in report.risk_flags:
        refs = ", ".join(risk.evidence_refs) or "无直接行情证据"
        lines.append(f"- [{risk.color}] {risk.risk_id}：{risk.trigger}（证据：{refs}）")
    lines.extend(["", "## 6. 下一步研究动作", ""])
    for action in report.next_research_actions:
        lines.append(f"- {action}")
    lines.extend(["", "## 7. 局限与免责声明", ""])
    for limitation in report.limitations:
        lines.append(f"- {limitation}")
    lines.extend(["", "仅供研究与教育，不构成个性化投资建议或交易指令；投资有风险。"])
    return "\n".join(lines)


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _reported_period(payload: dict[str, object]) -> str:
    for field in ("period", "frequency", "interval"):
        value = payload.get(field)
        if isinstance(value, str) and value:
            return value
    return "not_reported"


def _reported_adjustment(payload: dict[str, object]) -> str:
    for field in ("adjust", "adjustflag", "auto_adjust"):
        if field in payload:
            return f"{field}={payload[field]}"
    return "not_reported"


def _number(value: Decimal) -> int | float:
    rounded = value.quantize(Decimal("0.0001"))
    return int(rounded) if rounded == rounded.to_integral() else float(rounded)


def _percent_change(start: Decimal, end: Decimal) -> float | None:
    if start == 0:
        return None
    return round(float((end / start - 1) * Decimal("100")), 4)


def _max_drawdown(closes: Iterable[Decimal]) -> float | None:
    peak: Decimal | None = None
    maximum_drawdown = Decimal("0")
    for close in closes:
        peak = close if peak is None or close > peak else peak
        if peak != 0:
            maximum_drawdown = min(maximum_drawdown, (close / peak - 1) * Decimal("100"))
    return round(float(maximum_drawdown), 4) if peak is not None else None


def _annualized_volatility(closes: list[Decimal]) -> float | None:
    returns = [
        float((current / previous - 1) * Decimal("100"))
        for previous, current in zip(closes, closes[1:])
        if previous != 0
    ]
    if len(returns) < 2:
        return None
    return round(stdev(returns) * math.sqrt(252), 4)


def _relative_difference_percent(first: Decimal, second: Decimal) -> float | None:
    denominator = (abs(first) + abs(second)) / 2
    if denominator == 0:
        return None
    return float(abs(first - second) / denominator * Decimal("100"))


def _price_trend(period_return: float | None) -> str:
    if period_return is None:
        return "not_calculable"
    if period_return >= 5:
        return "upward"
    if period_return <= -5:
        return "downward"
    return "range_bound_or_mixed"


def _evidence_ref(index: int) -> str:
    return f"evidence:{index}"
