from __future__ import annotations

import unittest
from datetime import date

from ai_agent.analysis_tags import AnalysisScenario, Market
from ai_agent.application.input_parser import ResearchIntentParser


class ResearchIntentParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = ResearchIntentParser(today=lambda: date(2026, 7, 27))

    def test_a_share_history_request_normalizes_code_and_relative_range(self) -> None:
        intent = self.parser.parse("分析 sh.600519 最近三个月的走势")

        self.assertTrue(intent.is_ready)
        self.assertEqual(intent.symbol, "600519")
        self.assertEqual(intent.market, Market.A_SHARE)
        self.assertEqual(intent.scenario, AnalysisScenario.A_SHARE_PRICE_HISTORY)
        self.assertEqual((intent.start_date, intent.end_date), ("2026-04-27", "2026-07-27"))
        self.assertTrue(intent.assumptions)

    def test_global_quote_uses_global_scenario(self) -> None:
        intent = self.parser.parse("AAPL.US 最新报价")

        self.assertTrue(intent.is_ready)
        self.assertEqual(intent.symbol, "AAPL.US")
        self.assertEqual(intent.market, Market.GLOBAL)
        self.assertEqual(intent.scenario, AnalysisScenario.GLOBAL_MARKET_SNAPSHOT)

    def test_company_name_is_not_guessed_as_a_security(self) -> None:
        intent = self.parser.parse("分析贵州茅台最近三个月走势")

        self.assertFalse(intent.is_ready)
        self.assertIn("symbol", {item.field for item in intent.clarifications})
        self.assertIn("market", {item.field for item in intent.clarifications})

    def test_invalid_date_becomes_a_clarification_not_an_exception(self) -> None:
        intent = self.parser.parse("600519 2026-02-30 至 2026-03-01 走势")

        self.assertFalse(intent.is_ready)
        self.assertIn("date_range", {item.field for item in intent.clarifications})

    def test_report_request_requires_cross_source_validation(self) -> None:
        intent = self.parser.parse("给我 600000 最近30天的完整研究报告")

        self.assertEqual(intent.scenario, AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION)
        self.assertTrue(intent.is_ready)

    def test_global_valuation_request_is_not_sent_to_a_share_tool(self) -> None:
        intent = self.parser.parse("AAPL.US 估值")

        self.assertFalse(intent.is_ready)
        self.assertIn("scenario", {item.field for item in intent.clarifications})

    def test_history_request_without_a_time_expression_defaults_to_the_past_week(self) -> None:
        intent = self.parser.parse("分析 600519 走势")

        self.assertTrue(intent.is_ready)
        self.assertEqual((intent.start_date, intent.end_date), ("2026-07-20", "2026-07-27"))
        self.assertTrue(any("过去一周" in item for item in intent.assumptions))

    def test_vague_recent_expression_takes_precedence_over_the_default_period(self) -> None:
        intent = self.parser.parse("分析 600519 近期走势")

        self.assertTrue(intent.is_ready)
        self.assertEqual((intent.start_date, intent.end_date), ("2026-06-27", "2026-07-27"))
        self.assertTrue(any("近期/最近" in item for item in intent.assumptions))

    def test_explicit_dates_take_precedence_over_relative_or_default_windows(self) -> None:
        intent = self.parser.parse("分析 600519 最近 2026-01-02 至 2026-02-03 的走势")

        self.assertTrue(intent.is_ready)
        self.assertEqual((intent.start_date, intent.end_date), ("2026-01-02", "2026-02-03"))


if __name__ == "__main__":
    unittest.main()
