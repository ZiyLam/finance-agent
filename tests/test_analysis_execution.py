from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from ai_agent import cli
from ai_agent.analysis_execution import SecurityAnalysisExecutor
from ai_agent.analysis_tags import AnalysisScenario, Market
from ai_agent.research_planning import SecurityAnalysisRequest
from ai_agent.tools import FunctionTool, ToolRegistry


def _tool(name: str, handler) -> FunctionTool:
    return FunctionTool(name=name, description="test-only read-only tool", handler=handler)


def _risk_ids(result) -> set[str]:
    return {flag.risk_id for flag in result.risk_flags}


class SecurityAnalysisExecutionTests(unittest.TestCase):
    def test_a_share_history_primary_source_preserves_evidence_provenance(self) -> None:
        captured_arguments: list[dict[str, object]] = []

        def aktools(arguments):
            captured_arguments.append(dict(arguments))
            return json.dumps(
                {
                    "source": "AkTools (local AKShare service)",
                    "candles": [{"date": "2026-01-30", "close": "10.50"}],
                }
            )

        request = SecurityAnalysisRequest(
            symbol="600000",
            market=Market.A_SHARE,
            scenario=AnalysisScenario.A_SHARE_PRICE_HISTORY,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        result = SecurityAnalysisExecutor(ToolRegistry((_tool("aktools_market_data", aktools),))).execute(request)

        self.assertEqual(result.status, "complete")
        self.assertEqual(captured_arguments[0]["symbol"], "600000")
        self.assertEqual(captured_arguments[0]["start_date"], "20260101")
        self.assertEqual(captured_arguments[0]["end_date"], "20260131")
        self.assertEqual(len(result.evidence), 1)
        evidence = result.evidence[0]
        self.assertEqual(evidence.source, "aktools")
        self.assertEqual(evidence.priority, 1)
        self.assertEqual(evidence.raw_tool, "aktools_market_data")
        self.assertEqual(evidence.source_timestamp, "2026-01-30")
        self.assertEqual(evidence.freshness_tag, "historical")
        self.assertIn("NON_REALTIME_DATA", _risk_ids(result))
        self.assertNotIn("FALLBACK_SOURCE_USED", _risk_ids(result))

    def test_primary_error_uses_baostock_fallback_without_exposing_error_text(self) -> None:
        def primary_failure(_arguments):
            return "ERROR: example-token-that-must-not-be-emitted"

        def baostock(arguments):
            self.assertEqual(arguments["code"], "sh.600000")
            return json.dumps({"candles": [{"date": "2026-01-30", "close": "10.50"}]})

        request = SecurityAnalysisRequest(
            symbol="600000",
            market=Market.A_SHARE,
            scenario=AnalysisScenario.A_SHARE_PRICE_HISTORY,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        tools = ToolRegistry(
            (
                _tool("aktools_market_data", primary_failure),
                _tool("baostock_market_data", baostock),
            )
        )
        result = SecurityAnalysisExecutor(tools).execute(request)
        rendered = json.dumps(result.to_dict())

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.evidence[0].source, "baostock")
        self.assertEqual(result.evidence[0].priority, 4)
        self.assertIn("DATA_SOURCE_UNAVAILABLE", _risk_ids(result))
        self.assertIn("FALLBACK_SOURCE_USED", _risk_ids(result))
        self.assertNotIn("example-token-that-must-not-be-emitted", rendered)
        self.assertNotIn("token", rendered.lower())

    def test_cross_source_validation_requires_two_successful_evidence_records(self) -> None:
        def aktools(_arguments):
            return json.dumps({"candles": [{"date": "2026-01-30", "close": "10.50"}]})

        def baostock(_arguments):
            return json.dumps({"candles": [{"date": "2026-01-30", "close": "10.49"}]})

        request = SecurityAnalysisRequest(
            symbol="600000",
            market=Market.A_SHARE,
            scenario=AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        tools = ToolRegistry(
            (
                _tool("aktools_market_data", aktools),
                _tool("baostock_market_data", baostock),
            )
        )
        result = SecurityAnalysisExecutor(tools).execute(request)

        self.assertEqual(result.plan.required_successful_sources, 2)
        self.assertEqual(result.status, "complete")
        self.assertEqual([record.source for record in result.evidence], ["aktools", "baostock"])
        self.assertNotIn("INSUFFICIENT_EVIDENCE", _risk_ids(result))
        self.assertIn("FALLBACK_SOURCE_USED", _risk_ids(result))

    def test_missing_tools_produce_incomplete_evidence_result(self) -> None:
        request = SecurityAnalysisRequest(
            symbol="600000",
            market=Market.A_SHARE,
            scenario=AnalysisScenario.A_SHARE_PRICE_HISTORY,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        result = SecurityAnalysisExecutor(ToolRegistry()).execute(request)
        rendered = json.dumps(result.to_dict())

        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.evidence, ())
        self.assertIn("DATA_SOURCE_UNAVAILABLE", _risk_ids(result))
        self.assertIn("INSUFFICIENT_EVIDENCE", _risk_ids(result))
        self.assertNotIn("token", rendered.lower())

    def test_yfinance_end_date_is_converted_to_exclusive_upper_bound(self) -> None:
        captured_arguments: list[dict[str, object]] = []

        def yfinance(arguments):
            captured_arguments.append(dict(arguments))
            return json.dumps({"candles": [{"date": "2026-01-31", "close": "100.00"}]})

        request = SecurityAnalysisRequest(
            symbol="AAPL.US",
            market=Market.GLOBAL,
            scenario=AnalysisScenario.GLOBAL_PRICE_HISTORY,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        result = SecurityAnalysisExecutor(ToolRegistry((_tool("yfinance_market_data", yfinance),))).execute(
            request
        )

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.evidence[0].source, "yfinance")
        self.assertEqual(captured_arguments[0]["symbol"], "AAPL")
        self.assertEqual(captured_arguments[0]["start_date"], "2026-01-01")
        self.assertEqual(captured_arguments[0]["end_date"], "2026-02-01")

    def test_analyze_cli_does_not_initialize_the_configured_llm(self) -> None:
        def aktools(_arguments):
            return json.dumps({"candles": [{"date": "2026-01-30", "close": "10.50"}]})

        tool_registry = ToolRegistry((_tool("aktools_market_data", aktools),))
        output = io.StringIO()
        with (
            patch.object(cli, "_build_registered_tools", return_value=tool_registry) as build_tools,
            patch.dict(os.environ, {"AGENT_PROVIDER": "qianfan"}, clear=True),
            redirect_stdout(output),
        ):
            cli.main(
                [
                    "analyze",
                    "a_share_price_history",
                    "a_share",
                    "600000",
                    "2026-01-01",
                    "2026-01-31",
                ]
            )

        build_tools.assert_called_once_with(include_echo=False)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["plan"]["routing"]["model"]["provider"], "codex")


if __name__ == "__main__":
    unittest.main()
