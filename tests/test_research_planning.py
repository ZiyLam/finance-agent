from __future__ import annotations

import json
import unittest

from ai_agent.analysis_tags import AnalysisScenario, DataSourceTag, Market, ModelTag
from ai_agent.cli import run_route_command
from ai_agent.data_sources import get_data_source
from ai_agent.research_planning import SecurityAnalysisRequest, build_security_analysis_plan, catalog_snapshot


class ResearchPlanningTests(unittest.TestCase):
    def test_a_share_realtime_plan_uses_explicit_tagged_order(self) -> None:
        plan = build_security_analysis_plan(
            SecurityAnalysisRequest(
                symbol="600000",
                market=Market.A_SHARE,
                scenario=AnalysisScenario.A_SHARE_REALTIME_QUOTE,
            )
        )

        self.assertEqual(plan.primary_source.name, "biying")
        self.assertEqual([source.name for source in plan.fallback_sources], ["alltick"])
        self.assertEqual(plan.model.provider, "codex")
        self.assertIn("source_timestamp", plan.required_evidence_fields)
        self.assertIn("evidence_refs", plan.required_risk_fields)

    def test_global_history_plan_never_routes_to_a_share_only_source(self) -> None:
        plan = build_security_analysis_plan(
            SecurityAnalysisRequest(
                symbol="AAPL.US",
                market=Market.GLOBAL,
                scenario=AnalysisScenario.GLOBAL_PRICE_HISTORY,
                start_date="2026-01-01",
                end_date="2026-01-31",
            ),
            provider="qianfan",
        )

        routed_sources = [plan.primary_source, *plan.fallback_sources]
        self.assertEqual(plan.primary_source.name, "eodhd")
        self.assertNotIn("aktools", [source.name for source in routed_sources])
        self.assertTrue(
            all("global_markets" in source.tags for source in routed_sources),
        )
        self.assertEqual(plan.model.provider, "qianfan")

    def test_validation_requires_dates_and_compatible_model_tags(self) -> None:
        missing_dates = SecurityAnalysisRequest(
            symbol="600000",
            market=Market.A_SHARE,
            scenario=AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION,
        )
        with self.assertRaisesRegex(ValueError, "requires start_date"):
            build_security_analysis_plan(missing_dates)

        request = SecurityAnalysisRequest(
            symbol="600000",
            market=Market.A_SHARE,
            scenario=AnalysisScenario.A_SHARE_PRICE_HISTORY,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        with self.assertRaisesRegex(ValueError, "not suitable"):
            build_security_analysis_plan(request, provider="echo")

    def test_catalog_and_cli_expose_source_and_model_tags_without_credentials(self) -> None:
        snapshot = catalog_snapshot()
        biying = next(source for source in snapshot["data_sources"] if source["name"] == "biying")
        codex = next(model for model in snapshot["models"] if model["provider"] == "codex")

        self.assertIn(DataSourceTag.VALUATION_METRICS.value, biying["tags"])
        self.assertIn(ModelTag.AGENT_TOOL_PROTOCOL.value, codex["tags"])
        self.assertIn(AnalysisScenario.RESEARCH_BRIEF.value, [item["scenario"] for item in snapshot["scenarios"]])

        output: list[str] = []
        result = run_route_command(
            ["plan", "a_share_price_history", "a_share", "600000", "codex", "2026-01-01", "2026-01-31"],
            output=output.append,
        )

        self.assertEqual(result, 0)
        payload = json.loads(output[0])
        self.assertEqual(payload["contract_version"], "security-analysis-plan/v1")
        self.assertEqual(payload["routing"]["primary_source"]["name"], "aktools")
        self.assertNotIn("token", output[0].lower())


class TaggedDataSourceCatalogTests(unittest.TestCase):
    def test_tags_describe_only_exposed_adapter_capabilities(self) -> None:
        biying = get_data_source("biying")
        alpha_vantage = get_data_source("alphavantage")

        assert biying is not None and alpha_vantage is not None
        self.assertIn(DataSourceTag.REALTIME_QUOTE, biying.tags)
        self.assertIn(DataSourceTag.VALUATION_METRICS, biying.tags)
        self.assertIn(DataSourceTag.END_OF_DAY_QUOTE, alpha_vantage.tags)
        self.assertNotIn(DataSourceTag.REALTIME_QUOTE, alpha_vantage.tags)


if __name__ == "__main__":
    unittest.main()
