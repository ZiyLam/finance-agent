from __future__ import annotations

import json
import unittest
from datetime import date

from ai_agent.application.beginner_research import BeginnerResearchService
from ai_agent.application.index_research import (
    CSI_300,
    CSI_500,
    DAX,
    DOW_JONES,
    HANG_SENG,
    NASDAQ_100,
    NASDAQ_COMPOSITE,
    NIKKEI_225,
    SP_500,
    IndexResearchService,
    IndexResolver,
    professional_research_catalog,
)
from ai_agent.tools import FunctionTool, ToolRegistry


class IndexResearchTests(unittest.TestCase):
    def test_csi_500_is_resolved_from_a_natural_language_request(self) -> None:
        resolved = IndexResolver().resolve("请全面分析中证500近期表现")

        self.assertEqual(resolved, CSI_500)

    def test_other_reviewed_indices_use_the_same_direct_research_path(self) -> None:
        self.assertEqual(IndexResolver().resolve("沪深300"), CSI_300)

    def test_professional_catalog_supports_reviewed_well_known_global_indices(self) -> None:
        resolver = IndexResolver()
        catalog = professional_research_catalog()

        self.assertEqual(resolver.resolve("恒生指数"), HANG_SENG)
        self.assertEqual(resolver.resolve("S&P 500"), SP_500)
        self.assertEqual(resolver.resolve("纳指"), NASDAQ_COMPOSITE)
        self.assertEqual(resolver.resolve("纳指100"), NASDAQ_100)
        self.assertEqual(resolver.resolve("道指"), DOW_JONES)
        self.assertEqual(resolver.resolve("日经225"), NIKKEI_225)
        self.assertEqual(resolver.resolve("德国 DAX"), DAX)
        self.assertEqual(
            [market["key"] for market in catalog["markets"]],
            ["a_share", "hong_kong", "us", "japan", "europe"],
        )
        index_keys = [index["key"] for index in catalog["indices"]]
        self.assertEqual(len(index_keys), 18)
        self.assertIn("hang_seng", index_keys)
        self.assertIn("sp_500", index_keys)
        self.assertIn("nasdaq_composite", index_keys)

    def test_index_overview_uses_one_market_data_read_and_keeps_unconnected_data_explicit(self) -> None:
        calls: list[dict[str, object]] = []

        def market_data(arguments: dict[str, object]) -> str:
            calls.append(arguments)
            return json.dumps(
                {
                    "source": "index fixture",
                    "candles": [
                        {"date": "2026-07-21", "close": "5000", "high": "5010", "low": "4990"},
                        {"date": "2026-07-22", "close": "5015", "high": "5020", "low": "5000"},
                    ],
                }
            )

        beginner = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (FunctionTool("yfinance_market_data", "index fixture", market_data),)
            ),
            today=lambda: date(2026, 7, 22),
        )
        snapshot = IndexResearchService(beginner).overview(CSI_500)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["symbol"], "000905.SS")
        self.assertEqual(snapshot["index"]["display_name"], "中证 500")  # type: ignore[index]
        self.assertEqual(snapshot["market_data"]["status"], "complete")  # type: ignore[index]
        self.assertEqual(snapshot["valuation_style"]["status"], "reference_profile")  # type: ignore[index]
        self.assertEqual(snapshot["constituent_industries"]["status"], "reference_profile")  # type: ignore[index]
        self.assertEqual(snapshot["market_sentiment"]["label"], "中性")  # type: ignore[index]
        self.assertEqual(snapshot["market_sentiment"]["tone"], "flat")  # type: ignore[index]
        self.assertIn("一次日线读取", snapshot["limitations"][0])  # type: ignore[index]

    def test_index_overview_uses_zhitu_when_it_is_the_available_index_reader(self) -> None:
        calls: list[dict[str, object]] = []

        def zhitu_market_data(arguments: dict[str, object]) -> str:
            calls.append(arguments)
            return json.dumps(
                {
                    "source": "智兔数服",
                    "candles": [{"date": "2026-07-22", "close": "5000", "high": "5010", "low": "4990"}],
                }
            )

        beginner = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (FunctionTool("zhitu_market_data", "index fixture", zhitu_market_data),)
            ),
            today=lambda: date(2026, 7, 22),
        )

        snapshot = IndexResearchService(beginner).overview(CSI_500)

        self.assertEqual(calls[0]["action"], "index_history")
        self.assertEqual(calls[0]["symbol"], "000905.SH")
        self.assertEqual(snapshot["market_data"]["source"], "智兔数服")  # type: ignore[index]

    def test_static_only_professional_metrics_do_not_read_market_data(self) -> None:
        calls: list[object] = []
        beginner = BeginnerResearchService(
            tool_registry_factory=lambda: ToolRegistry(
                (FunctionTool("yfinance_market_data", "unexpected", calls.append),)
            )
        )

        snapshot = IndexResearchService(beginner).overview(
            CSI_300,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            metrics=("valuation_style", "risks"),
        )

        self.assertEqual(calls, [])
        self.assertNotIn("market_data", snapshot)
        self.assertIn("valuation_style", snapshot)
        self.assertIn("risks", snapshot)
        self.assertNotIn("constituent_industries", snapshot)


if __name__ == "__main__":
    unittest.main()
