from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
import unittest
from unittest.mock import patch

from ai_agent import cli
from ai_agent.analysis_execution import SecurityAnalysisExecutor
from ai_agent.analysis_tags import AnalysisScenario, Market
from ai_agent.research_planning import SecurityAnalysisRequest
from ai_agent.research_report import SecurityResearchReportBuilder
from ai_agent.tools import FunctionTool, ToolRegistry


def _tool(name: str, handler) -> FunctionTool:
    return FunctionTool(name=name, description="test-only read-only tool", handler=handler)


def _history(candles) -> str:
    return json.dumps({"candles": candles})


def _a_share_validation_result(baostock_candles):
    aktools_candles = [
        {"date": "2026-01-01", "open": "10", "high": "10", "low": "9.8", "close": "10", "volume": "100"},
        {"date": "2026-01-02", "open": "10", "high": "11.2", "low": "10", "close": "11", "volume": "110"},
        {"date": "2026-01-03", "open": "11", "high": "11", "low": "8.8", "close": "9", "volume": "120"},
        {"date": "2026-01-04", "open": "9", "high": "12.2", "low": "9", "close": "12", "volume": "130"},
    ]
    tools = ToolRegistry(
        (
            _tool("aktools_market_data", lambda _arguments: _history(aktools_candles)),
            _tool("baostock_market_data", lambda _arguments: _history(baostock_candles)),
        )
    )
    request = SecurityAnalysisRequest(
        symbol="600000",
        market=Market.A_SHARE,
        scenario=AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION,
        start_date="2026-01-01",
        end_date="2026-01-04",
    )
    return SecurityAnalysisExecutor(tools).execute(request)


class SecurityResearchReportTests(unittest.TestCase):
    def test_report_calculates_market_metrics_and_consistent_cross_source_check(self) -> None:
        result = _a_share_validation_result(
            [
                {"date": "2026-01-01", "close": "10.05", "high": "10.05", "low": "9.8", "volume": "100"},
                {"date": "2026-01-02", "close": "11.05", "high": "11.2", "low": "10", "volume": "110"},
                {"date": "2026-01-03", "close": "9.05", "high": "11", "low": "8.8", "volume": "120"},
                {"date": "2026-01-04", "close": "12.05", "high": "12.2", "low": "9", "volume": "130"},
            ]
        )
        report = SecurityResearchReportBuilder().build(result)
        payload = report.to_dict()
        risk_ids = {flag["risk_id"] for flag in payload["risk_flags"]}

        self.assertEqual(payload["contract_version"], "security-research-report/v1")
        self.assertEqual(payload["report_status"], "complete")
        self.assertEqual(payload["confidence"], "medium")
        self.assertEqual(len(payload["market_observations"]), 2)
        primary = payload["market_observations"][0]
        self.assertEqual(primary["period_return_percent"], 20.0)
        self.assertEqual(primary["max_drawdown_percent"], -18.1818)
        self.assertIsNotNone(primary["annualized_volatility_percent"])
        self.assertEqual(primary["reported_period"], "not_reported")
        self.assertEqual(primary["reported_adjustment"], "not_reported")
        self.assertEqual(payload["cross_source_checks"][0]["status"], "consistent")
        self.assertIn("FUNDAMENTAL_EVIDENCE_MISSING", risk_ids)
        self.assertIn("NON_REALTIME_DATA", risk_ids)
        self.assertIn("[B｜aktools", payload["report_markdown"])
        self.assertIn("仅供研究与教育", payload["report_markdown"])

    def test_report_marks_cross_source_divergence_and_historical_drawdown(self) -> None:
        result = _a_share_validation_result(
            [
                {"date": "2026-01-01", "close": "12", "high": "12", "low": "11", "volume": "100"},
                {"date": "2026-01-02", "close": "13", "high": "13", "low": "12", "volume": "110"},
                {"date": "2026-01-03", "close": "6", "high": "6", "low": "5", "volume": "120"},
                {"date": "2026-01-04", "close": "14", "high": "14", "low": "13", "volume": "130"},
            ]
        )
        report = SecurityResearchReportBuilder().build(result)
        risk_ids = {flag.risk_id for flag in report.risk_flags}

        self.assertEqual(report.cross_source_checks[0]["status"], "requires_review")
        self.assertEqual(report.confidence, "low")
        self.assertIn("CROSS_SOURCE_CLOSE_DIVERGENCE", risk_ids)
        self.assertIn("ELEVATED_HISTORICAL_DRAWDOWN", risk_ids)

    def test_report_refuses_to_overstate_when_no_usable_price_series_exists(self) -> None:
        tools = ToolRegistry((_tool("aktools_market_data", lambda _arguments: "{}"),))
        request = SecurityAnalysisRequest(
            symbol="600000",
            market=Market.A_SHARE,
            scenario=AnalysisScenario.A_SHARE_PRICE_HISTORY,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        report = SecurityResearchReportBuilder().build(SecurityAnalysisExecutor(tools).execute(request))
        risk_ids = {flag.risk_id for flag in report.risk_flags}

        self.assertEqual(report.confidence, "low")
        self.assertIn("USABLE_PRICE_HISTORY_MISSING", risk_ids)
        self.assertIn("No usable historical price series", report.summary)
        self.assertIn("No price-based scenario", report.scenarios[0]["research_implication"])

    def test_report_cli_uses_deterministic_report_path_without_initializing_llm(self) -> None:
        candles = [
            {"date": "2026-01-01", "close": "10", "high": "10", "low": "10", "volume": "100"},
            {"date": "2026-01-02", "close": "11", "high": "11", "low": "10", "volume": "110"},
        ]
        tool_registry = ToolRegistry(
            (
                _tool("aktools_market_data", lambda _arguments: _history(candles)),
                _tool("baostock_market_data", lambda _arguments: _history(candles)),
            )
        )
        output = io.StringIO()
        with (
            patch.object(cli, "_build_registered_tools", return_value=tool_registry) as build_tools,
            patch.dict(os.environ, {"AGENT_PROVIDER": "qianfan"}, clear=True),
            redirect_stdout(output),
        ):
            cli.main(["report", "a_share", "600000", "2026-01-01", "2026-01-02"])

        build_tools.assert_called_once_with(include_echo=False)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["contract_version"], "security-research-report/v1")
        self.assertEqual(payload["report_status"], "complete")
        self.assertNotIn("token", output.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
